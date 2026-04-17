import json
import logging
from datetime import datetime, timedelta
from db import (
    create_ai_claim, get_worker_risk, upsert_worker_risk, 
    check_duplicate_claim, get_db_connection
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [AGENTIC-ENGINE] [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def calculate_risk_score(worker_id, user_id, inactivity_minutes=0, has_movement_anomaly=False, is_in_danger_zone=False):
    """
    Calculate dynamic risk score based on multiple factors.
    Returns: (risk_score, risk_level, ai_status, reasons)
    """
    logger.info(f"[RISK-CALCULATION] Starting for worker {worker_id}")
    
    risk = 0
    reasons = []
    
    # Factor 1: Inactivity (40 points max)
    if inactivity_minutes > 25:
        risk += 40
        reasons.append(f"No movement for {inactivity_minutes} minutes")
        logger.debug(f"Inactivity detected: +40 points")
    elif inactivity_minutes > 15:
        risk += 20
        reasons.append(f"Low activity: {inactivity_minutes} minutes")
        logger.debug(f"Low activity: +20 points")
    
    # Factor 2: Movement anomaly (30 points max)
    if has_movement_anomaly:
        risk += 30
        reasons.append("Abnormal movement pattern detected")
        logger.debug(f"Movement anomaly detected: +30 points")
    
    # Factor 3: Dangerous zone (35 points max)
    if is_in_danger_zone:
        risk += 35
        reasons.append("Entered unsafe zone")
        logger.debug(f"Danger zone detected: +35 points")
    
    # Cap at 100
    risk = min(risk, 100)
    
    # Determine risk level and AI status
    if risk >= 70:
        risk_level = "HIGH"
        ai_status = "CRITICAL"
    elif risk >= 40:
        risk_level = "MEDIUM"
        ai_status = "WARNING"
    else:
        risk_level = "LOW"
        ai_status = "SAFE"
    
    logger.info(f"[RISK-CALCULATION] Final score: {risk} ({risk_level}) - Reasons: {reasons}")
    return risk, risk_level, ai_status, reasons


def process_worker_event(worker_id, user_id, location_lat, location_lng, 
                        inactivity_minutes=0, has_movement_anomaly=False, 
                        is_in_danger_zone=False):
    """
    Central AI processing pipeline for worker events.
    
    Process flow:
    1. Receive worker event (GPS, inactivity, anomalies)
    2. Fetch worker's historical risk state
    3. Calculate risk score
    4. Determine if claim should be triggered
    5. Create AI claim if risk > 70
    6. Return decision with full audit trail
    
    Args:
        worker_id: Worker ID
        user_id: User ID in database
        location_lat, location_lng: Current worker location
        inactivity_minutes: Minutes inactive
        has_movement_anomaly: Boolean
        is_in_danger_zone: Boolean
    
    Returns:
        dict with processing result and decision
    """
    logger.info(f"[WORKER-EVENT] Processing event for worker {worker_id}")
    logger.info(f"[WORKER-EVENT] Location: ({location_lat}, {location_lng})")
    logger.info(f"[WORKER-EVENT] Inactivity: {inactivity_minutes}min, Anomaly: {has_movement_anomaly}, DangerZone: {is_in_danger_zone}")
    
    try:
        # Step 1: Fetch previous worker state
        logger.info(f"[WORKER-STATE] Fetching historical risk state for worker {worker_id}")
        previous_risk_data = get_worker_risk(user_id)
        
        if previous_risk_data:
            logger.info(f"[WORKER-STATE] Previous risk: {previous_risk_data['current_risk_score']} ({previous_risk_data['risk_level']})")
        else:
            logger.info(f"[WORKER-STATE] No previous state found - starting fresh")
        
        # Step 2: Calculate risk score using agentic logic
        logger.info(f"[AGENTIC-DECISION] Analyzing worker signals...")
        risk_score, risk_level, ai_status, reasons = calculate_risk_score(
            worker_id, user_id,
            inactivity_minutes, has_movement_anomaly, is_in_danger_zone
        )
        
        # Step 3: Update worker risk state in database
        logger.info(f"[STATE-UPDATE] Storing risk state: {risk_score} ({risk_level}/{ai_status})")
        upsert_worker_risk(user_id, risk_score, risk_level, ai_status, json.dumps(reasons))
        
        # Step 4: Determine claim trigger decision
        claim_created = False
        claim_id = None
        decision_reason = ""
        
        if risk_score > 70:
            logger.warning(f"[CLAIM-DECISION] Risk score {risk_score} exceeds threshold (70)")
            
            # Check for duplicate claims
            logger.info(f"[DUPLICATE-CHECK] Checking for duplicate claims within 5-minute window...")
            duplicate = check_duplicate_claim(user_id, time_window_minutes=5)
            
            if duplicate:
                logger.warning(f"[CLAIM-DECISION] Duplicate claim prevented. Previous claim: {duplicate['claim_id']}")
                decision_reason = f"Duplicate prevention: recent claim {duplicate['claim_id']}"
                claim_created = False
                claim_id = duplicate['claim_id']
            else:
                # Step 5: Create AI-generated claim through formal pipeline
                logger.info(f"[CLAIM-CREATION] AI decision: CREATE CLAIM")
                logger.info(f"[CLAIM-CREATION] Trigger reason: High risk score {risk_score}")
                logger.info(f"[CLAIM-CREATION] Risk factors: {', '.join(reasons)}")
                
                claim = create_ai_claim(
                    user_id=user_id,
                    worker_id=f"W-{worker_id}",
                    location_lat=location_lat,
                    location_lng=location_lng,
                    reason="; ".join(reasons),
                    distress_condition="HIGH_RISK_DETECTED",
                    ai_confidence=min(100, risk_score),
                    detection_signals=json.dumps(reasons)
                )
                
                claim_created = True
                claim_id = claim['claim_id']
                decision_reason = f"High risk score {risk_score} triggered automatic claim creation"
                
                logger.info(f"[CLAIM-CREATED] Claim ID: {claim_id}")
                logger.info(f"[CLAIM-CREATED] Source: AI_GENERATED")
                logger.info(f"[CLAIM-CREATED] Status: PENDING")
                logger.info(f"[CLAIM-CREATED] Confidence: {min(100, risk_score)}%")
        else:
            logger.info(f"[CLAIM-DECISION] Risk score {risk_score} below threshold (70) - No claim triggered")
            decision_reason = f"Risk score {risk_score} below threshold. Status: {ai_status}"
        
        # Step 6: Return full audit trail
        result = {
            'status': 'success',
            'worker_id': worker_id,
            'user_id': user_id,
            'timestamp': datetime.utcnow().isoformat(),
            'risk_score': risk_score,
            'risk_level': risk_level,
            'ai_status': ai_status,
            'risk_factors': reasons,
            'claim_triggered': claim_created,
            'claim_id': claim_id,
            'decision': decision_reason,
            'location': {
                'lat': location_lat,
                'lng': location_lng
            }
        }
        
        logger.info(f"[PROCESSING-COMPLETE] Event processed - Decision: {'CLAIM_CREATED' if claim_created else 'NO_ACTION'}")
        return result
        
    except Exception as e:
        logger.error(f"[PROCESSING-ERROR] Error processing worker event: {str(e)}", exc_info=True)
        return {
            'status': 'error',
            'worker_id': worker_id,
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }


def simulate_ai_trigger(worker_id, user_id, location_lat=0.0, location_lng=0.0):
    """
    Simulate high-risk scenario for testing AI agentic behavior.
    
    Forces AI to calculate max risk and trigger claim creation.
    """
    logger.info(f"[TEST-SIMULATION] Simulating high-risk scenario for worker {worker_id}")
    
    return process_worker_event(
        worker_id=worker_id,
        user_id=user_id,
        location_lat=location_lat,
        location_lng=location_lng,
        inactivity_minutes=30,  # High inactivity
        has_movement_anomaly=True,  # Anomaly detected
        is_in_danger_zone=True  # In danger zone
    )


def get_ai_processing_log():
    """
    Retrieve recent AI processing decisions for debugging.
    """
    logger.info(f"[DEBUG] Retrieving AI processing history")
    return {
        'timestamp': datetime.utcnow().isoformat(),
        'message': 'AI processing history would be stored in centralized log system'
    }
