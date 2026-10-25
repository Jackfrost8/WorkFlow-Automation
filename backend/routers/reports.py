from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user
from backend.database import get_db
from backend.models.user import User
from backend.services.audit_service import log_audit_event
from backend.services.report_service import (
    REPORT_TYPES,
    build_and_export_report,
    get_application_pendency_data,
    get_document_validity_data,
    get_evc_status_data,
    get_overdue_cases_data,
    parse_and_validate_date_filters,
    validate_user_scope_and_region,
)

router = APIRouter(prefix="/reports", tags=["Reporting & Exports"])


@router.get(
    "/types",
    summary="List supported report types and available filter definitions",
    status_code=status.HTTP_200_OK,
)
def get_report_types(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retrieve list of supported reports and formats."""
    return {
        "supported_types": [
            {
                "key": key,
                "title": title,
                "supported_formats": ["csv", "pdf"],
            }
            for key, title in REPORT_TYPES.items()
        ],
        "formats": ["csv", "pdf"],
    }


@router.get(
    "/export",
    summary="Export compliance and workflow report in CSV or PDF format",
    status_code=status.HTTP_200_OK,
)
def export_report(
    report_type: str = Query(..., description="Report type identifier"),
    format: str = Query(default="csv", description="Output format ('csv' or 'pdf')"),
    start_date: Optional[str] = Query(default=None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(default=None, description="End date (YYYY-MM-DD)"),
    region: Optional[str] = Query(default=None, description="Geographic region filter"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate and download CSV or PDF report.
    Automatically scopes query to requesting user's institutional or regional authorization boundary.
    """
    content_bytes, media_type, filename = build_and_export_report(
        db=db,
        user=current_user,
        report_type=report_type,
        export_format=format,
        start_date=start_date,
        end_date=end_date,
        region=region,
    )

    # Log audit event
    clean_type = report_type.lower().strip()
    clean_fmt = format.lower().strip()
    log_audit_event(
        db=db,
        action="REPORT_EXPORTED",
        resource_type="REPORT",
        resource_id=clean_type,
        user_id=current_user.id,
        details={
            "report_type": clean_type,
            "format": clean_fmt,
            "filename": filename,
            "region_filter": region,
            "start_date": start_date,
            "end_date": end_date,
        },
    )
    db.commit()

    return Response(
        content=content_bytes,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )


@router.get(
    "/preview",
    summary="Preview report tabular data in JSON before downloading",
    status_code=status.HTTP_200_OK,
)
def preview_report(
    report_type: str = Query(..., description="Report type identifier"),
    start_date: Optional[str] = Query(default=None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(default=None, description="End date (YYYY-MM-DD)"),
    region: Optional[str] = Query(default=None, description="Geographic region filter"),
    limit: int = Query(default=25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve JSON preview of report contents for dashboard tables."""
    clean_type = report_type.lower().strip()
    if clean_type not in REPORT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported report type '{report_type}'.",
        )

    start_dt, end_dt = parse_and_validate_date_filters(start_date, end_date)
    effective_region = validate_user_scope_and_region(current_user, region)

    if clean_type == "application_pendency":
        data, col_map, _ = get_application_pendency_data(
            db, current_user, start_dt, end_dt, effective_region
        )
    elif clean_type == "overdue_cases":
        data, col_map, _ = get_overdue_cases_data(
            db, current_user, start_dt, end_dt, effective_region
        )
    elif clean_type == "document_validity":
        data, col_map, _ = get_document_validity_data(
            db, current_user, start_dt, end_dt, effective_region
        )
    elif clean_type == "evc_status":
        data, col_map, _ = get_evc_status_data(
            db, current_user, start_dt, end_dt, effective_region
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid report type.")

    return {
        "report_type": clean_type,
        "title": REPORT_TYPES[clean_type],
        "total_records": len(data),
        "columns": [{"key": k, "label": v} for k, v in col_map.items()],
        "rows": data[:limit],
    }
