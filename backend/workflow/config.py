"""
Centralized workflow routes configuration and initialization for AICTE.
"""
from typing import Dict, List
from sqlalchemy.orm import Session
from backend.models.workflow import StageTransition, WorkflowRoute, WorkflowStage

DEFAULT_WORKFLOW_ROUTES = {
    "ONLY_SCRUTINY": {
        "name": "Only Scrutiny Approval Route",
        "description": "Streamlined approval via Regional Scrutiny directly to Final Decision.",
        "stages": [
            {
                "stage_key": "SCRUTINY",
                "name": "Scrutiny Committee Review",
                "order_index": 1,
                "sla_days": 7,
                "authorized_roles": "REGIONAL_OFFICER,BUREAU_OFFICER",
                "is_evc_stage": False,
                "is_final": False,
            },
            {
                "stage_key": "DECISION",
                "name": "Final Committee Decision",
                "order_index": 2,
                "sla_days": 5,
                "authorized_roles": "REGIONAL_OFFICER,BUREAU_OFFICER",
                "is_evc_stage": False,
                "is_final": True,
            },
        ],
    },
    "SCRUTINY_EVC": {
        "name": "Scrutiny with EVC Inspection Route",
        "description": "Standard approval path: Scrutiny followed by EVC Physical Inspection to Decision.",
        "stages": [
            {
                "stage_key": "SCRUTINY",
                "name": "Scrutiny Committee Review",
                "order_index": 1,
                "sla_days": 7,
                "authorized_roles": "REGIONAL_OFFICER,BUREAU_OFFICER",
                "is_evc_stage": False,
                "is_final": False,
            },
            {
                "stage_key": "EVC",
                "name": "Expert Visit Committee (EVC)",
                "order_index": 2,
                "sla_days": 10,
                "authorized_roles": "REGIONAL_OFFICER,BUREAU_OFFICER",
                "is_evc_stage": True,
                "is_final": False,
            },
            {
                "stage_key": "DECISION",
                "name": "Final Committee Decision",
                "order_index": 3,
                "sla_days": 5,
                "authorized_roles": "REGIONAL_OFFICER,BUREAU_OFFICER",
                "is_evc_stage": False,
                "is_final": True,
            },
        ],
    },
    "EVC_SAC": {
        "name": "EVC with Standing Appeal Committee Route",
        "description": "Appellate pathway: EVC Inspection followed by SAC Hearing to Decision.",
        "stages": [
            {
                "stage_key": "EVC",
                "name": "Expert Visit Committee (EVC)",
                "order_index": 1,
                "sla_days": 10,
                "authorized_roles": "REGIONAL_OFFICER,BUREAU_OFFICER",
                "is_evc_stage": True,
                "is_final": False,
            },
            {
                "stage_key": "SAC",
                "name": "Standing Appeal Committee (SAC)",
                "order_index": 2,
                "sla_days": 7,
                "authorized_roles": "REGIONAL_OFFICER,BUREAU_OFFICER",
                "is_evc_stage": False,
                "is_final": False,
            },
            {
                "stage_key": "DECISION",
                "name": "Final Committee Decision",
                "order_index": 3,
                "sla_days": 5,
                "authorized_roles": "REGIONAL_OFFICER,BUREAU_OFFICER",
                "is_evc_stage": False,
                "is_final": True,
            },
        ],
    },
    "ONLY_EVC": {
        "name": "Direct EVC Inspection Route",
        "description": "Fast-tracked verification route: Direct EVC Inspection to Decision.",
        "stages": [
            {
                "stage_key": "EVC",
                "name": "Expert Visit Committee (EVC)",
                "order_index": 1,
                "sla_days": 10,
                "authorized_roles": "REGIONAL_OFFICER,BUREAU_OFFICER",
                "is_evc_stage": True,
                "is_final": False,
            },
            {
                "stage_key": "DECISION",
                "name": "Final Committee Decision",
                "order_index": 2,
                "sla_days": 5,
                "authorized_roles": "REGIONAL_OFFICER,BUREAU_OFFICER",
                "is_evc_stage": False,
                "is_final": True,
            },
        ],
    },
}


def ensure_default_workflow_routes(db: Session) -> Dict[str, WorkflowRoute]:
    """
    Idempotently creates or updates the 4 configured workflow routes, their stages, and transitions.
    """
    route_map: Dict[str, WorkflowRoute] = {}

    for route_code, config in DEFAULT_WORKFLOW_ROUTES.items():
        route = db.query(WorkflowRoute).filter(WorkflowRoute.code == route_code).first()
        if not route:
            route = WorkflowRoute(
                code=route_code,
                name=config["name"],
                description=config["description"],
                is_active=True,
            )
            db.add(route)
            db.flush()
        else:
            route.name = config["name"]
            route.description = config["description"]
            route.is_active = True

        route_map[route_code] = route

        # Sync stages
        stage_objs: List[WorkflowStage] = []
        for stage_data in config["stages"]:
            stage = (
                db.query(WorkflowStage)
                .filter(
                    WorkflowStage.route_id == route.id,
                    WorkflowStage.stage_key == stage_data["stage_key"],
                )
                .first()
            )
            if not stage:
                stage = WorkflowStage(
                    route_id=route.id,
                    **stage_data,
                )
                db.add(stage)
                db.flush()
            else:
                for k, v in stage_data.items():
                    setattr(stage, k, v)

            stage_objs.append(stage)

        # Sort stages by order_index
        stage_objs.sort(key=lambda s: s.order_index)

        # Sync transitions: Forward transitions between consecutive stages
        for i in range(len(stage_objs) - 1):
            curr_s = stage_objs[i]
            next_s = stage_objs[i + 1]
            existing_trans = (
                db.query(StageTransition)
                .filter(
                    StageTransition.route_id == route.id,
                    StageTransition.from_stage_id == curr_s.id,
                    StageTransition.to_stage_id == next_s.id,
                    StageTransition.action_name == "FORWARD",
                )
                .first()
            )
            if not existing_trans:
                db.add(
                    StageTransition(
                        route_id=route.id,
                        from_stage_id=curr_s.id,
                        to_stage_id=next_s.id,
                        action_name="FORWARD",
                        requires_remarks=False,
                    )
                )

            # Return transition backwards
            existing_ret = (
                db.query(StageTransition)
                .filter(
                    StageTransition.route_id == route.id,
                    StageTransition.from_stage_id == next_s.id,
                    StageTransition.to_stage_id == curr_s.id,
                    StageTransition.action_name == "RETURN",
                )
                .first()
            )
            if not existing_ret:
                db.add(
                    StageTransition(
                        route_id=route.id,
                        from_stage_id=next_s.id,
                        to_stage_id=curr_s.id,
                        action_name="RETURN",
                        requires_remarks=True,
                    )
                )

    db.commit()
    return route_map
