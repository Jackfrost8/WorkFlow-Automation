import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from fastapi import HTTPException, status
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from backend.core.time_service import get_effective_date, get_effective_time
from backend.models.application import Application
from backend.models.evc import EVCStatus, EVCVisit
from backend.models.notification import TrackableEntityType
from backend.models.document import UndertakingDocument
from backend.models.user import Institution, User, UserRole
from backend.services.deadline_service import get_trackable_items

REPORT_TYPES = {
    "application_pendency": "Application Pendency Report",
    "overdue_cases": "Overdue Statutory Cases Report",
    "document_validity": "Document Validity & Expiry Report",
    "evc_status": "Expert Visit Committee (EVC) Status Report",
}


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and stamp total page count in footer."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_footer(num_pages)
            super().showPage()
        super().save()

    def draw_footer(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        # Footer text
        footer_text = f"Page {self._pageNumber} of {page_count}  |  AICTE Workflow Platform  |  Official & Confidential"
        self.drawRightString(842 - 20, 15, footer_text)
        self.drawString(20, 15, "Generated under statutory authority of AICTE Regulations")
        self.restoreState()


def sanitize_cell_for_csv(val: Any) -> Any:
    """
    Prevent Spreadsheet Formula Injection (CSV injection).
    Prepends a single quote if the string begins with =, +, -, @, \\t, or \\r.
    """
    if isinstance(val, str) and len(val) > 0:
        if val[0] in ("=", "+", "-", "@", "\t", "\r"):
            return f"'{val}"
    return val


def parse_and_validate_date_filters(
    start_date: Optional[str],
    end_date: Optional[str],
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Validate and parse ISO date query strings."""
    start_dt = None
    end_dt = None
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid start_date format. Expected YYYY-MM-DD.",
            )
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid end_date format. Expected YYYY-MM-DD.",
            )

    if start_dt and end_dt and start_dt > end_dt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be later than end_date.",
        )

    return start_dt, end_dt


def get_region_str(reg: Any) -> Optional[str]:
    """Extract string value of region safely whether string or enum."""
    if reg is None:
        return None
    if hasattr(reg, "value"):
        return str(reg.value)
    return str(reg)


def validate_user_scope_and_region(
    user: User,
    requested_region: Optional[str],
) -> Optional[str]:
    """
    Enforce geographic and institutional boundaries on reporting queries.
    """
    if user.role == UserRole.REGIONAL_OFFICER:
        user_reg = get_region_str(user.region)
        if requested_region and user_reg:
            req_clean = requested_region.strip().upper()
            u_clean = user_reg.strip().upper()
            if req_clean not in u_clean and u_clean not in req_clean:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: Regional officers may only export reports for their assigned region ({user_reg}).",
                )
        return user_reg

    if user.role in (UserRole.ADMIN, UserRole.BUREAU_OFFICER):
        return requested_region.strip() if requested_region else None

    # Institution role handles scoping via institution_id
    return None


# =====================================================================
# DATA RETRIEVAL FOR REPORTS
# =====================================================================


def get_application_pendency_data(
    db: Session,
    user: User,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    region_filter: Optional[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, str], List[float]]:
    """Retrieve application pendency records scoped by role."""
    now_effective = get_effective_time(db)

    query = db.query(Application).join(Institution, Application.institution_id == Institution.id)

    if user.role == UserRole.INSTITUTION:
        query = query.filter(Application.institution_id == user.institution_id)
    elif user.role == UserRole.REGIONAL_OFFICER:
        query = query.filter(Institution.region.ilike(user.region))
    elif region_filter:
        query = query.filter(Institution.region.ilike(region_filter))

    if start_dt:
        query = query.filter(Application.created_at >= start_dt)
    if end_dt:
        query = query.filter(Application.created_at <= end_dt)

    apps = query.order_by(Application.created_at.desc()).all()

    col_map = {
        "app_num": "App Number",
        "title": "Proposal Title",
        "institution": "Institution",
        "region": "Region",
        "route": "Route",
        "stage": "Current Stage",
        "status": "Status",
        "deadline": "Stage Deadline",
        "days_in_stage": "Days in Stage",
    }
    widths = [90.0, 180.0, 150.0, 55.0, 65.0, 100.0, 65.0, 55.0, 42.0]

    rows = []
    for app in apps:
        inst_name = app.institution.name if app.institution else f"Inst #{app.institution_id}"
        reg_val = get_region_str(app.institution.region) if app.institution else "N/A"
        route_name = app.route.name if app.route else "Standard Route"
        stage_name = app.current_stage.name if app.current_stage else "Completed"
        deadline_str = (
            app.current_stage_deadline.strftime("%Y-%m-%d")
            if app.current_stage_deadline
            else "N/A"
        )

        stage_entered = app.updated_at or app.created_at
        if stage_entered:
            stage_tz = (
                stage_entered
                if stage_entered.tzinfo is not None
                else stage_entered.replace(tzinfo=timezone.utc)
            )
            days_in_stage = max(0, round((now_effective - stage_tz).total_seconds() / 86400.0, 1))
        else:
            days_in_stage = 0.0

        rows.append(
            {
                "app_num": app.application_number,
                "title": app.title,
                "institution": inst_name,
                "region": reg_val,
                "route": route_name,
                "stage": stage_name,
                "status": app.status.value,
                "deadline": deadline_str,
                "days_in_stage": days_in_stage,
            }
        )

    return rows, col_map, widths


def get_overdue_cases_data(
    db: Session,
    user: User,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    region_filter: Optional[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, str], List[float]]:
    """Retrieve overdue items across stages, EVCs, undertakings, and documents."""
    effective_date = get_effective_date(db)

    col_map = {
        "entity_type": "Entity Type",
        "ref_id": "Reference ID",
        "title": "Item Description",
        "institution": "Institution",
        "region": "Region",
        "due_date": "Due Date",
        "days_overdue": "Days Overdue",
        "status": "Status",
    }
    widths = [90.0, 80.0, 220.0, 160.0, 60.0, 65.0, 65.0, 62.0]

    all_items = []
    for et in TrackableEntityType:
        all_items.extend(get_trackable_items(db, et))

    rows = []
    for item in all_items:
        # Authorization scope check
        if user.role == UserRole.INSTITUTION:
            if item.institution_id != user.institution_id:
                continue
        elif user.role == UserRole.REGIONAL_OFFICER:
            item_reg = get_region_str(item.region)
            user_reg = get_region_str(user.region)
            if not item_reg or not user_reg or item_reg.strip().upper() != user_reg.strip().upper():
                continue
        elif region_filter:
            item_reg = get_region_str(item.region)
            if not item_reg or item_reg.strip().upper() != region_filter.strip().upper():
                continue

        if not item.due_date:
            continue

        item_d = item.due_date.date() if isinstance(item.due_date, datetime) else item.due_date
        diff_days = (item_d - effective_date).days
        if diff_days >= 0:
            continue  # Not overdue

        # Date filter check against statutory due date
        if start_dt and item_d < start_dt.date():
            continue
        if end_dt and item_d > end_dt.date():
            continue

        inst = db.query(Institution).filter(Institution.id == item.institution_id).first()
        inst_name = inst.name if inst else f"Inst #{item.institution_id}"
        reg_val = get_region_str(inst.region) if inst and inst.region else "N/A"

        rows.append(
            {
                "entity_type": item.entity_type.value,
                "ref_id": str(item.entity_id),
                "title": item.title,
                "institution": inst_name,
                "region": reg_val,
                "due_date": item_d.strftime("%Y-%m-%d"),
                "days_overdue": abs(diff_days),
                "status": "OVERDUE",
            }
        )

    # Sort most overdue first
    rows.sort(key=lambda x: x["days_overdue"], reverse=True)
    return rows, col_map, widths


def get_document_validity_data(
    db: Session,
    user: User,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    region_filter: Optional[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, str], List[float]]:
    """Retrieve compliance documents, leases, and expiry metrics."""
    now_effective = get_effective_time(db)
    query = db.query(UndertakingDocument).join(
        Institution, UndertakingDocument.institution_id == Institution.id
    )

    if user.role == UserRole.INSTITUTION:
        query = query.filter(UndertakingDocument.institution_id == user.institution_id)
    elif user.role == UserRole.REGIONAL_OFFICER:
        query = query.filter(Institution.region.ilike(user.region))
    elif region_filter:
        query = query.filter(Institution.region.ilike(region_filter))

    if start_dt:
        query = query.filter(UndertakingDocument.created_at >= start_dt)
    if end_dt:
        query = query.filter(UndertakingDocument.created_at <= end_dt)

    docs = query.order_by(UndertakingDocument.expiry_date.asc().nulls_last()).all()

    col_map = {
        "doc_id": "Doc ID",
        "institution": "Institution",
        "region": "Region",
        "doc_type": "Document Type",
        "title": "Document Title",
        "file_name": "File Name",
        "issue_date": "Issue Date",
        "expiry_date": "Expiry Date",
        "validity": "Validity",
    }
    widths = [45.0, 160.0, 55.0, 95.0, 180.0, 95.0, 55.0, 55.0, 62.0]

    rows = []
    for doc in docs:
        inst_name = doc.institution.name if doc.institution else f"Inst #{doc.institution_id}"
        reg_val = get_region_str(doc.institution.region) if doc.institution and doc.institution.region else "N/A"
        issue_str = doc.issue_date.strftime("%Y-%m-%d") if doc.issue_date else "N/A"
        expiry_str = doc.expiry_date.strftime("%Y-%m-%d") if doc.expiry_date else "Perpetual"

        # Validity determination
        if doc.expiry_date:
            exp_tz = (
                doc.expiry_date
                if doc.expiry_date.tzinfo is not None
                else doc.expiry_date.replace(tzinfo=timezone.utc)
            )
            diff_days = (exp_tz - now_effective).total_seconds() / 86400.0
            if diff_days < 0:
                validity = f"EXPIRED ({abs(round(diff_days))}d ago)"
            elif diff_days <= 30:
                validity = f"EXPIRING ({round(diff_days)}d left)"
            else:
                validity = "ACTIVE"
        else:
            validity = "ACTIVE"

        rows.append(
            {
                "doc_id": str(doc.id),
                "institution": inst_name,
                "region": reg_val,
                "doc_type": doc.doc_type.value,
                "title": doc.title,
                "file_name": doc.file_name,
                "issue_date": issue_str,
                "expiry_date": expiry_str,
                "validity": validity,
            }
        )

    return rows, col_map, widths


def get_evc_status_data(
    db: Session,
    user: User,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    region_filter: Optional[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, str], List[float]]:
    """Retrieve EVC inspection records, scheduled teams, and delay flags."""
    effective_date = get_effective_date(db)
    query = (
        db.query(EVCVisit)
        .join(Application, EVCVisit.application_id == Application.id)
        .join(Institution, Application.institution_id == Institution.id)
    )

    if user.role == UserRole.INSTITUTION:
        query = query.filter(Application.institution_id == user.institution_id)
    elif user.role == UserRole.REGIONAL_OFFICER:
        query = query.filter(Institution.region.ilike(user.region))
    elif region_filter:
        query = query.filter(Institution.region.ilike(region_filter))

    if start_dt:
        query = query.filter(EVCVisit.created_at >= start_dt)
    if end_dt:
        query = query.filter(EVCVisit.created_at <= end_dt)

    visits = query.order_by(EVCVisit.id.desc()).all()

    col_map = {
        "visit_id": "Visit ID",
        "app_num": "App Number",
        "institution": "Institution",
        "region": "Region",
        "status": "Visit Status",
        "due_date": "Due Date",
        "scheduled_date": "Scheduled Date",
        "team_lead": "Team Lead",
        "experts": "Experts",
    }
    widths = [50.0, 85.0, 170.0, 55.0, 80.0, 60.0, 65.0, 130.0, 107.0]

    rows = []
    for v in visits:
        app = v.application
        inst = app.institution if app else None
        inst_name = inst.name if inst else "N/A"
        reg_val = get_region_str(inst.region) if inst and inst.region else "N/A"
        app_num = app.application_number if app else f"App #{v.application_id}"

        due_str = v.due_date.strftime("%Y-%m-%d") if v.due_date else "N/A"
        sched_str = v.scheduled_date.strftime("%Y-%m-%d") if v.scheduled_date else "Pending"

        is_delayed = False
        if v.status != EVCStatus.COMPLETED and v.due_date:
            due_d = v.due_date.date() if isinstance(v.due_date, datetime) else v.due_date
            if due_d < effective_date:
                is_delayed = True

        status_text = f"{v.status.value} [DELAYED]" if is_delayed else v.status.value

        rows.append(
            {
                "visit_id": str(v.id),
                "app_num": app_num,
                "institution": inst_name,
                "region": reg_val,
                "status": status_text,
                "due_date": due_str,
                "scheduled_date": sched_str,
                "team_lead": v.committee_lead_name or "Unassigned",
                "experts": v.committee_members_json or "None",
            }
        )

    return rows, col_map, widths


# =====================================================================
# FORMAT EXPORTERS (CSV & PDF)
# =====================================================================


def generate_csv_report(
    data: List[Dict[str, Any]],
    column_mapping: Dict[str, str],
) -> str:
    """
    Generate CSV using Pandas DataFrame with formula injection protection.
    """
    ordered_headers = list(column_mapping.values())
    if not data:
        df = pd.DataFrame(columns=ordered_headers)
        return df.to_csv(index=False)

    renamed_data = []
    for row in data:
        renamed_row = {}
        for key, header in column_mapping.items():
            val = row.get(key, "")
            val = sanitize_cell_for_csv(val)
            renamed_row[header] = val
        renamed_data.append(renamed_row)

    df = pd.DataFrame(renamed_data)
    # Double-check all string columns for CSV formula injection
    for col in df.columns:
        df[col] = df[col].apply(sanitize_cell_for_csv)

    return df.to_csv(index=False)


def generate_pdf_report(
    data: List[Dict[str, Any]],
    column_mapping: Dict[str, str],
    col_widths: List[float],
    report_title: str,
    user: User,
    effective_date_str: str,
    filter_summary: str,
) -> bytes:
    """
    Generate professional landscape A4 PDF report with ReportLab.
    Includes AICTE header, dynamic metadata, wrapped table cells, and page numbering.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=20,
        rightMargin=20,
        topMargin=20,
        bottomMargin=30,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=16,
        textColor=colors.HexColor("#1E3A8A"),
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#334155"),
    )
    meta_style = ParagraphStyle(
        "DocMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#475569"),
    )
    th_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.white,
    )
    td_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#0F172A"),
    )
    empty_style = ParagraphStyle(
        "EmptyCell",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=9,
        leading=12,
        alignment=1,  # Centered
        textColor=colors.HexColor("#64748B"),
    )

    elements = []

    # Title block
    elements.append(Paragraph("ALL INDIA COUNCIL FOR TECHNICAL EDUCATION", title_style))
    elements.append(Paragraph(report_title.upper(), subtitle_style))
    elements.append(Spacer(1, 4))

    # Metadata block
    actor_desc = f"{user.full_name} ({user.role.value}"
    if user.role == UserRole.REGIONAL_OFFICER and user.region:
        actor_desc += f" - {get_region_str(user.region)} Region"
    actor_desc += ")"

    meta_text = (
        f"<b>Generated By:</b> {actor_desc}  |  "
        f"<b>Effective System Date:</b> {effective_date_str}  |  "
        f"<b>Filter Scope:</b> {filter_summary}  |  "
        f"<b>Records Count:</b> {len(data)}"
    )
    elements.append(Paragraph(meta_text, meta_style))
    elements.append(Spacer(1, 8))

    # Build Table
    headers = [Paragraph(h, th_style) for h in column_mapping.values()]
    table_data = [headers]

    if not data:
        empty_row = [
            Paragraph("No records found matching the specified filter criteria.", empty_style)
        ] + [""] * (len(headers) - 1)
        table_data.append(empty_row)
        table = Table(table_data, colWidths=col_widths)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
                    ("SPAN", (0, 1), (-1, 1)),
                    ("ALIGN", (0, 1), (-1, 1), "CENTER"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 1), (-1, 1), 14),
                    ("BOTTOMPADDING", (0, 1), (-1, 1), 14),
                ]
            )
        )
    else:
        for idx, row in enumerate(data):
            cell_row = []
            for key in column_mapping.keys():
                val = str(row.get(key, ""))
                cell_row.append(Paragraph(val, td_style))
            table_data.append(cell_row)

        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        t_style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
        # Alternating row background colors
        for i in range(1, len(table_data)):
            bg = colors.HexColor("#F8FAFC") if i % 2 == 1 else colors.white
            t_style.append(("BACKGROUND", (0, i), (-1, i), bg))

        table.setStyle(TableStyle(t_style))

    elements.append(table)
    doc.build(elements, canvasmaker=NumberedCanvas)
    return buffer.getvalue()


def build_and_export_report(
    db: Session,
    user: User,
    report_type: str,
    export_format: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    region: Optional[str] = None,
) -> Tuple[bytes, str, str]:
    """
    Orchestrate report generation and return (content_bytes, media_type, filename).
    """
    clean_type = report_type.lower().strip()
    if clean_type not in REPORT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported report type '{report_type}'. Supported types: {list(REPORT_TYPES.keys())}",
        )

    clean_format = export_format.lower().strip()
    if clean_format not in ("csv", "pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{export_format}'. Supported formats: 'csv', 'pdf'",
        )

    start_dt, end_dt = parse_and_validate_date_filters(start_date, end_date)
    effective_region = validate_user_scope_and_region(user, region)
    effective_date = get_effective_date(db)

    # Retrieve data
    if clean_type == "application_pendency":
        data, col_map, widths = get_application_pendency_data(
            db, user, start_dt, end_dt, effective_region
        )
    elif clean_type == "overdue_cases":
        data, col_map, widths = get_overdue_cases_data(db, user, start_dt, end_dt, effective_region)
    elif clean_type == "document_validity":
        data, col_map, widths = get_document_validity_data(
            db, user, start_dt, end_dt, effective_region
        )
    elif clean_type == "evc_status":
        data, col_map, widths = get_evc_status_data(db, user, start_dt, end_dt, effective_region)
    else:
        raise HTTPException(status_code=400, detail="Invalid report type.")

    # Filter summary for header
    filters = []
    if effective_region:
        filters.append(f"Region: {effective_region}")
    if user.role == UserRole.INSTITUTION:
        inst = db.query(Institution).filter(Institution.id == user.institution_id).first()
        filters.append(f"Institution: {inst.name if inst else user.institution_id}")
    if start_date or end_date:
        filters.append(f"Date Range: {start_date or 'Earliest'} to {end_date or 'Latest'}")
    filter_summary = ", ".join(filters) if filters else "All Records in Authorized Scope"

    title = REPORT_TYPES[clean_type]
    file_prefix = f"aicte_{clean_type}_{effective_date.strftime('%Y%m%d')}"

    if clean_format == "csv":
        csv_str = generate_csv_report(data, col_map)
        return csv_str.encode("utf-8"), "text/csv", f"{file_prefix}.csv"

    # PDF format
    pdf_bytes = generate_pdf_report(
        data=data,
        column_mapping=col_map,
        col_widths=widths,
        report_title=title,
        user=user,
        effective_date_str=effective_date.strftime("%Y-%m-%d"),
        filter_summary=filter_summary,
    )
    return pdf_bytes, "application/pdf", f"{file_prefix}.pdf"
