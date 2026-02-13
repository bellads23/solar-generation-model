import os
import time
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# =====================================================
# LOAD ENV VARIABLES
# =====================================================

load_dotenv()

API_KEY = os.getenv("API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

MODEL1_API_URL = os.getenv("MODEL1_API_URL")
MODEL1_API_KEY = os.getenv("MODEL1_API_KEY")
MODEL1_TIMEOUT = int(os.getenv("MODEL1_TIMEOUT", 30))

MODEL2_API_URL = os.getenv("MODEL2_API_URL")
MODEL2_API_KEY = os.getenv("MODEL2_API_KEY")
MODEL2_TIMEOUT = int(os.getenv("MODEL2_TIMEOUT", 30))

MODEL3_API_URL = os.getenv("MODEL3_API_URL")
MODEL3_API_KEY = os.getenv("MODEL3_API_KEY")
MODEL3_TIMEOUT = int(os.getenv("MODEL3_TIMEOUT", 30))

MIN_SOLAR_SCORE = float(os.getenv("MIN_SOLAR_SCORE", 6))
MIN_SUITABILITY_SCORE = float(os.getenv("MIN_SUITABILITY_SCORE", 6))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", 70))
MAX_ROI_YEARS = float(os.getenv("MAX_ROI_YEARS", 7))

# =====================================================
# APP + RATE LIMITING
# =====================================================

app = Flask(__name__)
limiter = Limiter(get_remote_address, app=app, default_limits=["100 per minute"])

# =====================================================
# DATABASE CONNECTION
# =====================================================

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)


# =====================================================
# AUTHENTICATION
# =====================================================

@app.before_request
def require_api_key():
    if request.headers.get("X-API-KEY") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401


# =====================================================
# MAIN ENDPOINT
# =====================================================


# @app.route( "/api/v1/roi | Methods: ['POST']")
#@limiter.limit("100 per minute")
# Try this order:
@app.route("/api/v1/roi", methods=["POST"])
# @limiter.limit("100 per minute")  <-- Comment this out for 1 minute to test
def solar_assessment():

    start_time = time.time()
    session = Session()

    try:
        data = request.get_json()

        if not data:
            return jsonify({"error": "Invalid JSON"}), 400

        # ----------------------------
        # Basic Input Validation
        # ----------------------------
        if data.get("monthly_energy_usage_kwh", 0) < 0:
            return jsonify({"error": "Energy usage cannot be negative"}), 400

        if data.get("monthly_energy_cost", 0) < 0:
            return jsonify({"error": "Energy cost cannot be negative"}), 400

        # =====================================================
        # 1️ SAVE BUSINESS
        # =====================================================

        business_result = session.execute(text("""
            INSERT INTO business (
                business_name, location, latitude, longitude,
                monthly_energy_usage_kwh, monthly_energy_cost,
                roof_area_sqm, business_type
            )
            VALUES (
                :name, :location, :lat, :lon,
                :usage, :cost, :roof, :type
            )
            RETURNING id
        """), {
            "name": data["business_name"],
            "location": data["location"],
            "lat": data["latitude"],
            "lon": data["longitude"],
            "usage": data["monthly_energy_usage_kwh"],
            "cost": data["monthly_energy_cost"],
            "roof": data["roof_area_sqm"],
            "type": data["business_type"]
        })

        business_id = business_result.fetchone()[0]

        # =====================================================
        # 2️ CALL MODEL 1 (Solar)
        # =====================================================

        m1_response = requests.post(
            MODEL1_API_URL,
            json=data,
            headers={"X-API-KEY": MODEL1_API_KEY},
            timeout=MODEL1_TIMEOUT
        )

        solar_data = m1_response.json()

        solar_result = session.execute(text("""
            INSERT INTO solar_analysis (
                business_id,
                solar_irradiance_kwh_m2_day,
                annual_sunshine_hours,
                optimal_panel_angle,
                shading_factor,
                solar_potential_score,
                model_confidence
            )
            VALUES (
                :bid, :irr, :sun, :angle, :shade, :score, :conf
            )
            RETURNING id
        """), {
            "bid": business_id,
            "irr": solar_data["solar_irradiance_kwh_m2_day"],
            "sun": solar_data["annual_sunshine_hours"],
            "angle": solar_data["optimal_panel_angle"],
            "shade": solar_data["shading_factor"],
            "score": solar_data["solar_potential_score"],
            "conf": solar_data["model_confidence"]
        })

        solar_id = solar_result.fetchone()[0]

        # =====================================================
        # 3️ CALL MODEL 2 (Cost)
        # =====================================================

        m2_response = requests.post(
            MODEL2_API_URL,
            json=data,
            headers={"X-API-KEY": MODEL2_API_KEY},
            timeout=MODEL2_TIMEOUT
        )

        cost_data = m2_response.json()

        cost_result = session.execute(text("""
            INSERT INTO cost_analysis (
                business_id,
                system_size_kw,
                installation_cost,
                annual_energy_production_kwh,
                annual_savings,
                roi_years,
                payback_period_years,
                net_present_value,
                incentives_available
            )
            VALUES (
                :bid, :size, :install, :prod, :save,
                :roi, :payback, :npv, :inc
            )
            RETURNING id
        """), {
            "bid": business_id,
            "size": cost_data["system_size_kw"],
            "install": cost_data["installation_cost"],
            "prod": cost_data["annual_energy_production_kwh"],
            "save": cost_data["annual_savings"],
            "roi": cost_data["roi_years"],
            "payback": cost_data["payback_period_years"],
            "npv": cost_data["net_present_value"],
            "inc": cost_data["incentives_available"]
        })

        cost_id = cost_result.fetchone()[0]

        # =====================================================
        # 4️⃣ CALL MODEL 3 (Suitability)
        # =====================================================

        m3_response = requests.post(
            MODEL3_API_URL,
            json=data,
            headers={"X-API-KEY": MODEL3_API_KEY},
            timeout=MODEL3_TIMEOUT
        )

        suit_data = m3_response.json()

        suit_result = session.execute(text("""
            INSERT INTO business_suitability (
                business_id,
                business_hours_match_score,
                energy_pattern_compatibility,
                roof_suitability_score,
                maintenance_capacity_score,
                overall_suitability_score,
                risk_factors,
                opportunities
            )
            VALUES (
                :bid, :hours, :energy, :roof, :maint,
                :overall, :risk, :opp
            )
            RETURNING id
        """), {
            "bid": business_id,
            "hours": suit_data["business_hours_match_score"],
            "energy": suit_data["energy_pattern_compatibility"],
            "roof": suit_data["roof_suitability_score"],
            "maint": suit_data["maintenance_capacity_score"],
            "overall": suit_data["overall_suitability_score"],
            "risk": suit_data["risk_factors"],
            "opp": suit_data["opportunities"]
        })

        suit_id = suit_result.fetchone()[0]

        # =====================================================
        #  DECISION ENGINE
        # =====================================================

        solar_viable = (
            solar_data["solar_potential_score"] >= MIN_SOLAR_SCORE and
            suit_data["overall_suitability_score"] >= MIN_SUITABILITY_SCORE and
            cost_data["roi_years"] <= MAX_ROI_YEARS and
            solar_data["model_confidence"] >= MIN_CONFIDENCE
        )

        recommendation = "Solar installation recommended." if solar_viable else "Solar not recommended."

        # =====================================================
        # SAVE FINAL RECOMMENDATION
        # =====================================================

        session.execute(text("""
            INSERT INTO final_recommendation (
                business_id,
                solar_analysis_id,
                cost_analysis_id,
                business_suitability_id,
                solar_viable,
                recommended_system_size_kw,
                estimated_roi_years,
                confidence_score,
                recommendation_summary,
                key_reasons,
                warnings,
                next_steps
            )
            VALUES (
                :bid, :sid, :cid, :bsid,
                :viable, :size, :roi,
                :conf, :summary,
                :reasons, :warnings, :steps
            )
        """), {
            "bid": business_id,
            "sid": solar_id,
            "cid": cost_id,
            "bsid": suit_id,
            "viable": solar_viable,
            "size": cost_data["system_size_kw"],
            "roi": cost_data["roi_years"],
            "conf": solar_data["model_confidence"],
            "summary": recommendation,
            "reasons": ["Strong solar exposure"],
            "warnings": ["Seasonal variability"],
            "steps": ["Schedule site inspection"]
        })

        execution_time = int((time.time() - start_time) * 1000)

        session.commit()

        return jsonify({
            "business_id": business_id,
            "solar_viable": solar_viable,
            "message": recommendation,
            "execution_time_ms": execution_time
        }), 200

    except Exception:
        session.rollback()
        return jsonify({"error": "Internal Server Error"}), 500

    finally:
        session.close()

if __name__ == "__main__":
    # This loop will print every route the server actually knows
    print("\n--- DETECTED ROUTES BY FLASK ---")
    for rule in app.url_map.iter_rules():
        print(f"Path: {rule.rule} | Methods: {rule.methods}")
    print("---------------------------------\n")

    app.run(
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", 8000)),
        debug=True  # Turn debug ON for now to help us
    )

