from __future__ import annotations

from datetime import datetime, date, timedelta, time
from fractions import Fraction
from html import escape
from io import BytesIO, StringIO
import csv
from zoneinfo import ZoneInfo
import os
import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from supabase import Client, create_client

st.set_page_config(page_title="Shukriya's Kitchen Orders", page_icon="🍽️", layout="centered")

# Responsive presentation: desktop table + mobile cart cards.
st.markdown(
    """
    <style>
    /* Desktop is the default. */
    .st-key-cart_mobile { display: none; }

    /* Manager notification bell. A dynamic style adds the red dot only when needed. */
    .st-key-manager_notification_bell button {
        min-width: 3rem;
        font-size: 1.15rem;
    }

    @media (max-width: 700px) {
        /* Give the ordering UI more room on phones. */
        [data-testid="stAppViewBlockContainer"] {
            padding-left: 0.85rem !important;
            padding-right: 0.85rem !important;
            padding-top: 1.15rem !important;
        }
        h1 { font-size: 2rem !important; line-height: 1.15 !important; }
        h2 { font-size: 1.55rem !important; }
        h3 { font-size: 1.3rem !important; }

        .st-key-cart_desktop { display: none !important; }
        .st-key-cart_mobile { display: block !important; }

        /* Keep the small quantity-control rows horizontal on mobile. */
        .st-key-cart_mobile [data-testid="stHorizontalBlock"] {
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            gap: 0.35rem !important;
        }
        .st-key-cart_mobile [data-testid="stColumn"] {
            min-width: 0 !important;
        }
        .st-key-cart_mobile button {
            min-height: 2.55rem !important;
            padding: 0.25rem 0.45rem !important;
        }
        .st-key-cart_mobile p { margin-bottom: 0 !important; }
    }

    @media (min-width: 701px) {
        .st-key-cart_desktop { display: block !important; }
        .st-key-cart_mobile { display: none !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def setting(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


def nested_secret(section: str, name: str, default: str = "") -> str:
    try:
        return str(st.secrets[section].get(name, default))
    except Exception:
        return default


def first_secret(*names: str) -> str:
    for name in names:
        try:
            value = st.secrets.get(name, "")
            if value is not None and str(value).strip():
                return str(value).strip()
        except Exception:
            pass
        value = os.environ.get(name, "")
        if value.strip():
            return value.strip()
    return ""


BUSINESS_NAME = setting("BUSINESS_NAME", "Shukriya's Kitchen")
BUSINESS_PHONE = setting("BUSINESS_PHONE", "")
BUSINESS_ADDRESS = setting("BUSINESS_ADDRESS", "")
CURRENCY = setting("CURRENCY", "$")
APP_TIMEZONE = setting("APP_TIMEZONE", "America/Los_Angeles")
APP_PASSWORD = setting("APP_PASSWORD", "")

SUPABASE_URL = (first_secret("SUPABASE_URL", "supabase_url") or nested_secret("supabase", "url")).strip()
SUPABASE_SECRET_KEY = (
    first_secret("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY", "supabase_secret_key")
    or nested_secret("supabase", "secret_key")
    or nested_secret("supabase", "service_role_key")
).strip()


@st.cache_resource
def get_db() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


@st.cache_data(ttl=30, show_spinner=False)
def load_menu() -> pd.DataFrame:
    response = (
        get_db().table("menu")
        .select("id,dish,category,price,available,sale_mode,min_order_qty")
        .eq("available", True)
        .order("category").order("dish").execute()
    )
    df = pd.DataFrame(response.data or [])
    if df.empty:
        return pd.DataFrame(columns=["id", "dish", "category", "price", "available", "sale_mode", "min_order_qty"])
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["min_order_qty"] = pd.to_numeric(df.get("min_order_qty", 1), errors="coerce").fillna(1)
    return df.dropna(subset=["price"]).reset_index(drop=True)


@st.cache_data(ttl=30, show_spinner=False)
def load_public_menu() -> pd.DataFrame:
    response = (
        get_db().table("menu_options")
        .select("id,menu_item_id,label,price,active,sort_order,min_order_qty,menu!inner(id,dish,category,available,sale_mode,min_order_qty)")
        .eq("active", True)
        .eq("menu.available", True)
        .order("sort_order").execute()
    )
    rows = []
    for row in response.data or []:
        menu = row.get("menu") or {}
        rows.append({
            "option_id": int(row["id"]),
            "menu_item_id": int(row["menu_item_id"]),
            "dish": str(menu.get("dish", "")),
            "category": str(menu.get("category") or "Menu"),
            "option": str(row.get("label") or "Standard"),
            "price": float(row.get("price") or 0),
            "sort_order": int(row.get("sort_order") or 0),
            "sale_mode": str(menu.get("sale_mode") or "piece"),
            "min_order_qty": float(row.get("min_order_qty") or menu.get("min_order_qty") or 1),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=30, show_spinner=False)
def load_all_menu_items() -> pd.DataFrame:
    response = (
        get_db().table("menu")
        .select("id,dish,category,price,available,sale_mode,min_order_qty")
        .order("category").order("dish").execute()
    )
    df = pd.DataFrame(response.data or [])
    if df.empty:
        return pd.DataFrame(columns=["id", "dish", "category", "price", "available", "sale_mode", "min_order_qty"])
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["min_order_qty"] = pd.to_numeric(df.get("min_order_qty", 1), errors="coerce").fillna(1)
    return df.reset_index(drop=True)


def save_menu_item(menu_item_id: int | None, dish: str, category: str, available: bool, units: list[dict]) -> None:
    payload = {
        "p_menu_item_id": int(menu_item_id) if menu_item_id is not None else None,
        "p_dish": dish,
        "p_category": category,
        "p_available": bool(available),
        "p_units": units,
    }
    get_db().rpc("admin_save_menu_item_v3", payload).execute()
    load_menu.clear(); load_public_menu.clear(); load_all_menu_items.clear(); load_menu_option_details.clear()


@st.cache_data(ttl=30, show_spinner=False)
def load_menu_option_details(menu_item_id: int) -> list[dict]:
    r = (get_db().table("menu_options")
         .select("id,label,price,active,sort_order,min_order_qty")
         .eq("menu_item_id", int(menu_item_id))
         .order("sort_order").execute())
    return [
        {
            "id": int(x["id"]),
            "label": str(x.get("label") or ""),
            "price": float(x.get("price") or 0),
            "active": bool(x.get("active", True)),
            "sort_order": int(x.get("sort_order") or 0),
            "min_order_qty": float(x.get("min_order_qty") or 1),
        }
        for x in (r.data or [])
    ]


def load_menu_option_prices(menu_item_id: int) -> dict[str, float]:
    return {x["label"]: x["price"] for x in load_menu_option_details(menu_item_id) if x["active"]}


@st.cache_data(ttl=30, show_spinner=False)
def load_managers() -> list[str]:
    response = get_db().table("managers").select("name,active").eq("active", True).order("name").execute()
    return [str(row["name"]) for row in response.data or []]


@st.cache_data(ttl=30, show_spinner=False)
def load_store_settings() -> dict[str, str]:
    response = get_db().table("store_settings").select("key,value").execute()
    return {str(r["key"]): str(r.get("value") or "") for r in response.data or []}


def save_store_setting(key: str, value: str) -> None:
    get_db().table("store_settings").upsert({"key": key, "value": value.strip()}, on_conflict="key").execute()
    load_store_settings.clear()
    # Invoice rendering depends on kitchen settings such as the printed address.
    for cached_fn_name in ("build_invoice_pdf", "build_invoice_print_html"):
        cached_fn = globals().get(cached_fn_name)
        if cached_fn is not None and hasattr(cached_fn, "clear"):
            cached_fn.clear()


def kitchen_address() -> str:
    try:
        return load_store_settings().get("kitchen_address", "").strip() or BUSINESS_ADDRESS
    except Exception:
        return BUSINESS_ADDRESS


def default_hourly_salary() -> float:
    try:
        raw = load_store_settings().get("hourly_salary", "").strip()
        return max(0.0, float(raw)) if raw else 0.0
    except Exception:
        return 0.0


@st.cache_data(ttl=30, show_spinner=False)
def load_customers() -> pd.DataFrame:
    response = get_db().table("customers").select("id,name,normalized_name,short_code,phone").order("name").execute()
    df = pd.DataFrame(response.data or [])
    if df.empty:
        return pd.DataFrame(columns=["id","name","normalized_name","short_code","phone"])
    return df


def normalize_customer_name(name: str) -> str:
    return " ".join((name or "").strip().split()).casefold()


def existing_customer_record(name: str) -> dict:
    norm = normalize_customer_name(name)
    if not norm:
        return {}
    try:
        df = load_customers()
        match = df[df["normalized_name"].astype(str).str.casefold() == norm]
        return match.iloc[0].to_dict() if not match.empty else {}
    except Exception:
        return {}


def existing_customer_code(name: str) -> str:
    row = existing_customer_record(name)
    return str(row.get("short_code") or "")


def existing_customer_phone(name: str) -> str:
    row = existing_customer_record(name)
    return str(row.get("phone") or "")


def autofill_customer_contact(name_key: str, phone_key: str) -> None:
    name = str(st.session_state.get(name_key, "") or "")
    row = existing_customer_record(name)
    if row:
        st.session_state[phone_key] = str(row.get("phone") or "")


def resolve_customer_code(name: str, phone: str = "") -> str:
    clean = " ".join((name or "").strip().split())
    if not clean:
        return ""
    result = get_db().rpc("resolve_customer_code", {"p_name": clean, "p_phone": phone or None}).execute()
    row = (result.data or [{}])[0] if isinstance(result.data, list) else (result.data or {})
    code = str(row.get("resolved_short_code") or "")
    load_customers.clear()
    return code


@st.cache_data(show_spinner=False)
def delivery_time_options(start_hour: int = 8, end_hour: int = 22, step_minutes: int = 30) -> list[time]:
    out = []
    minutes = start_hour * 60
    end = end_hour * 60
    while minutes <= end:
        out.append(time(minutes // 60, minutes % 60))
        minutes += step_minutes
    return out


def format_delivery_date(d: date) -> str:
    return d.strftime("%a, %b %d, %Y")


def format_delivery_time(t: time) -> str:
    return datetime.combine(date.today(), t).strftime("%I:%M %p").lstrip("0")


@st.cache_data(ttl=15, show_spinner=False)
def load_active_announcements() -> list[dict]:
    response = (
        get_db().table("announcements")
        .select("id,title,message,level,active,created_at,updated_at")
        .eq("active", True)
        .order("updated_at", desc=True)
        .execute()
    )
    return list(response.data or [])


@st.cache_data(ttl=15, show_spinner=False)
def load_all_announcements() -> list[dict]:
    response = (
        get_db().table("announcements")
        .select("id,title,message,level,active,created_at,updated_at")
        .order("updated_at", desc=True)
        .execute()
    )
    return list(response.data or [])


def create_announcement(title: str, message: str, level: str, active: bool = True) -> None:
    get_db().table("announcements").insert({
        "title": title.strip() or "Announcement",
        "message": message.strip(),
        "level": level,
        "active": bool(active),
    }).execute()
    load_active_announcements.clear()
    load_all_announcements.clear()


def update_announcement(announcement_id: int, title: str, message: str, level: str, active: bool) -> None:
    get_db().table("announcements").update({
        "title": title.strip() or "Announcement",
        "message": message.strip(),
        "level": level,
        "active": bool(active),
    }).eq("id", int(announcement_id)).execute()
    load_active_announcements.clear()
    load_all_announcements.clear()


def render_customer_announcements() -> None:
    try:
        announcements = load_active_announcements()
    except Exception:
        announcements = []
    for ann in announcements:
        title = str(ann.get("title") or "Announcement")
        message = str(ann.get("message") or "").strip()
        if not message:
            continue
        body = f"**{title}**\n\n{message}"
        level = str(ann.get("level") or "Info")
        if level == "Warning":
            st.warning(body)
        elif level == "Success":
            st.success(body)
        elif level == "Important":
            st.error(body, icon="📣")
        else:
            st.info(body, icon="📣")


@st.cache_data(ttl=20, show_spinner=False)
def load_recent_orders(limit: int = 100) -> pd.DataFrame:
    response = (
        get_db().table("orders")
        .select("id,invoice_number,created_at,order_source,order_taker,customer,customer_code,phone,delivery_date,delivery_time,total,payment_status,payment_method,payment_received_by,paid_at,order_status")
        .order("created_at", desc=True).limit(limit).execute()
    )
    return pd.DataFrame(response.data or [])


def load_new_online_orders(limit: int = 25) -> list[dict]:
    """Fetch unprocessed customer orders for the manager notification bell."""
    response = (
        get_db().table("orders")
        .select("id,invoice_number,created_at,customer,total,order_status,order_source")
        .eq("order_source", "Online")
        .eq("order_status", "New")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(response.data or [])


def relative_time(value: str | datetime) -> str:
    dt = local_datetime(value)
    now = datetime.now(tz=dt.tzinfo)
    seconds = max(0, int((now - dt).total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hr ago" if hours == 1 else f"{hours} hrs ago"
    days = hours // 24
    return f"{days} day ago" if days == 1 else f"{days} days ago"


def parse_quantity(text: str) -> tuple[float, str]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Enter a quantity, for example 2, 1/2 tray, or 1 1/2 trays.")
    normalized = raw.lower().replace("trays", "tray").strip()
    number_text = normalized.replace("tray", "").strip()
    try:
        if " " in number_text and "/" in number_text:
            whole, frac = number_text.split(None, 1)
            value = float(whole) + float(Fraction(frac))
        elif "/" in number_text:
            value = float(Fraction(number_text))
        else:
            value = float(number_text)
    except Exception as exc:
        raise ValueError("Use a quantity like 2, 1/2, 1 tray, 1/2 tray, 1 1/2 trays, or 1.5 trays.") from exc
    if value <= 0:
        raise ValueError("Quantity must be greater than zero.")
    return round(value, 3), raw


def money(value: float) -> str:
    return f"{CURRENCY}{float(value):,.2f}"


def local_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    try:
        return dt.astimezone(ZoneInfo(APP_TIMEZONE))
    except Exception:
        return dt


def payment_details_for_invoice(order: dict) -> dict:
    status = str(order.get("payment_status") or "").strip() or "Unpaid"
    method = str(order.get("payment_method") or "").strip()
    receiver = str(order.get("payment_received_by") or "").strip()
    paid_at_raw = order.get("paid_at")
    paid_at = ""
    if paid_at_raw:
        try:
            paid_at = local_datetime(str(paid_at_raw)).strftime("%b %d, %Y %I:%M %p")
        except Exception:
            paid_at = str(paid_at_raw)
    return {
        "status": status,
        "is_paid": status.casefold() == "paid",
        "method": method,
        "receiver": receiver,
        "paid_at": paid_at,
    }


@st.cache_data(ttl=60, show_spinner=False)
def build_invoice_pdf(order: dict) -> bytes:
    """Create a compact, invoice-style PDF with minimal unused page space."""
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    payment = payment_details_for_invoice(order)

    # A5-like width is easy to read on phones and prints neatly.  The height is
    # calculated from the rendered content below, so a short order does not
    # create a mostly blank Letter-size page.
    page_width = 5.8 * inch
    side_margin = 0.28 * inch
    top_margin = 0.24 * inch
    bottom_margin = 0.24 * inch
    usable_width = page_width - (2 * side_margin)

    body = ParagraphStyle(
        "CompactBody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=8.2, leading=10.2, spaceAfter=0,
    )
    small = ParagraphStyle(
        "CompactSmall", parent=body, fontSize=7.4, leading=9,
        textColor=colors.HexColor("#4A4A4A"),
    )
    micro = ParagraphStyle(
        "CompactMicro", parent=body, fontSize=6.8, leading=8.2,
        textColor=colors.HexColor("#666666"),
    )
    business_style = ParagraphStyle(
        "CompactBusiness", parent=body, fontName="Helvetica-Bold",
        fontSize=14, leading=16,
    )
    invoice_style = ParagraphStyle(
        "CompactInvoice", parent=body, fontName="Helvetica-Bold",
        fontSize=11, leading=13, alignment=TA_RIGHT,
    )
    right_small = ParagraphStyle(
        "CompactRight", parent=small, alignment=TA_RIGHT,
    )
    total_style = ParagraphStyle(
        "CompactTotal", parent=body, fontName="Helvetica-Bold",
        fontSize=10, leading=12, alignment=TA_RIGHT,
    )

    story = []

    # Header: business identity on the left, invoice identity on the right.
    contact = "<br/>".join(escape(x) for x in [kitchen_address(), BUSINESS_PHONE] if x)
    business_block = escape(BUSINESS_NAME)
    if contact:
        business_block += f"<br/><font size='7' color='#666666'>{contact}</font>"
    invoice_block = (
        f"INVOICE<br/>"
        f"<font size='8'>#{escape(str(order['invoice_number']))}</font><br/>"
        f"<font size='7' color='#666666'>{escape(str(order['date']))}</font>"
    )
    header = Table(
        [[Paragraph(business_block, business_style), Paragraph(invoice_block, invoice_style)]],
        colWidths=[usable_width * 0.58, usable_width * 0.42],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    story.extend([header, Spacer(1, 5)])

    # Customer / order details.  Keep this deliberately compact and omit empty
    # fields so the invoice never wastes vertical space.
    customer_lines = []
    if order.get("customer"):
        customer_name = escape(str(order['customer']))
        code = str(order.get("customer_code") or "").strip()
        if code:
            customer_name += f" <b>({escape(code)})</b>"
        customer_lines.append(f"<b>Bill to:</b> {customer_name}")
    if order.get("phone"):
        customer_lines.append(escape(str(order["phone"])))
    if order.get("address"):
        customer_lines.append(escape(str(order["address"])))

    order_lines = []
    if order.get("order_source"):
        order_lines.append(f"<b>Source:</b> {escape(str(order['order_source']))}")
    if order.get("order_taker"):
        order_lines.append(f"<b>Taken by:</b> {escape(str(order['order_taker']))}")

    delivery_bits = []
    if order.get("delivery_date"):
        try:
            dd = date.fromisoformat(str(order["delivery_date"])).strftime("%A, %B %d, %Y")
        except Exception:
            dd = str(order["delivery_date"])
        delivery_bits.append(dd)
    if order.get("delivery_time"):
        rawt = str(order["delivery_time"])[:5]
        try:
            tt = datetime.strptime(rawt, "%H:%M").strftime("%I:%M %p").lstrip("0")
        except Exception:
            tt = rawt
        delivery_bits.append(tt)
    if delivery_bits:
        delivery_text = " &nbsp; | &nbsp; ".join(escape(x) for x in delivery_bits)
        story.extend([
            Table([[Paragraph(f"<b>DELIVERY: {delivery_text}</b>", ParagraphStyle(
                "DeliveryBanner", parent=body, fontName="Helvetica-Bold", fontSize=10.2, leading=12
            ))]], colWidths=[usable_width], style=TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#F3F3F3")),
                ("BOX", (0,0), (-1,-1), .7, colors.HexColor("#777777")),
                ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6),
                ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ])), Spacer(1, 5)
        ])

    if customer_lines or order_lines:
        details = Table(
            [[Paragraph("<br/>".join(customer_lines) or " ", small),
              Paragraph("<br/>".join(order_lines) or " ", right_small)]],
            colWidths=[usable_width * 0.62, usable_width * 0.38],
        )
        details.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.extend([details, Spacer(1, 3)])

    # Itemized charges: typical invoice styling with a light header and only
    # horizontal separators instead of a heavy full grid.
    rows = [["Item", "Qty", "Unit", "Amount"]]
    for item in order["items"]:
        rows.append([
            Paragraph(escape(str(item["dish"])), body),
            Paragraph(escape(str(item.get("quantity_label") or item["qty"])), right_small),
            Paragraph(money(item["price"]), right_small),
            Paragraph(money(item["line_total"]), right_small),
        ])

    item_table = Table(
        rows,
        colWidths=[usable_width * 0.46, usable_width * 0.17,
                   usable_width * 0.17, usable_width * 0.20],
        repeatRows=1,
    )
    item_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0F0F0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#333333")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#BDBDBD")),
    ]
    for row_no in range(1, len(rows)):
        item_style.append(("LINEBELOW", (0, row_no), (-1, row_no), 0.25, colors.HexColor("#E4E4E4")))
    item_table.setStyle(TableStyle(item_style))
    story.extend([item_table, Spacer(1, 5)])

    # Only show non-zero adjustments.  This keeps ordinary invoices very short.
    totals = [["Subtotal", money(order["subtotal"])]]
    if float(order.get("delivery_fee") or 0):
        totals.append(["Delivery", money(order["delivery_fee"])])
    if float(order.get("discount") or 0):
        totals.append(["Discount", f"-{money(order['discount'])}"])
    if float(order.get("tax_amount") or 0) or float(order.get("tax_percent") or 0):
        totals.append([f"Tax ({float(order['tax_percent']):.2f}%)", money(order["tax_amount"])])
    totals.append(["TOTAL", money(order["total"])])

    total_rows = []
    for idx, (label, value) in enumerate(totals):
        is_total = idx == len(totals) - 1
        total_rows.append([
            Paragraph(escape(str(label)), total_style if is_total else right_small),
            Paragraph(escape(str(value)), total_style if is_total else right_small),
        ])
    totals_table = Table(total_rows, colWidths=[usable_width * 0.78, usable_width * 0.22], hAlign="RIGHT")
    totals_style = [
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor("#666666")),
    ]
    totals_table.setStyle(TableStyle(totals_style))
    story.append(totals_table)

    if payment["is_paid"]:
        payment_lines = ["<b>PAYMENT STATUS:</b> PAID"]
        if payment["method"]:
            payment_lines.append(f"<b>Method:</b> {escape(payment['method'])}")
        if payment["receiver"]:
            payment_lines.append(f"<b>Received by:</b> {escape(payment['receiver'])}")
        if payment["paid_at"]:
            payment_lines.append(f"<b>Paid at:</b> {escape(payment['paid_at'])}")
        payment_table = Table(
            [[Paragraph("<br/>".join(payment_lines), small)]],
            colWidths=[usable_width],
            style=TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#F5FAF5")),
                ("BOX", (0,0), (-1,-1), 0.7, colors.HexColor("#3F7A4D")),
                ("LEFTPADDING", (0,0), (-1,-1), 6),
                ("RIGHTPADDING", (0,0), (-1,-1), 6),
                ("TOPPADDING", (0,0), (-1,-1), 4),
                ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ]),
        )
        story.extend([Spacer(1, 5), payment_table])

    if order.get("notes"):
        story.extend([
            Spacer(1, 5),
            Paragraph(f"<b>ORDER NOTES: {escape(str(order['notes']))}</b>", body),
        ])

    story.extend([
        Spacer(1, 7),
        Paragraph("Thank you for your order!", ParagraphStyle(
            "CompactThanks", parent=micro, alignment=TA_CENTER,
        )),
    ])

    # Measure the completed flowables at their actual available width.  Platypus
    # normally lays them on a fixed-size page; this pass lets us size the page to
    # the content instead.  Very large orders are capped at Letter height and
    # can naturally continue to a second page.
    measured_height = 0.0
    for flowable in story:
        try:
            _, h = flowable.wrap(usable_width, 10000)
            before = flowable.getSpaceBefore() if hasattr(flowable, "getSpaceBefore") else 0
            after = flowable.getSpaceAfter() if hasattr(flowable, "getSpaceAfter") else 0
            measured_height += h + before + after
        except Exception:
            measured_height += 12

    page_height = measured_height + top_margin + bottom_margin + 10
    page_height = max(4.2 * inch, min(page_height, 11 * inch))

    doc = SimpleDocTemplate(
        buffer,
        pagesize=(page_width, page_height),
        rightMargin=side_margin,
        leftMargin=side_margin,
        topMargin=top_margin,
        bottomMargin=bottom_margin,
        title=f"Invoice {order['invoice_number']}",
        author=BUSINESS_NAME,
    )

    def draw_paid_watermark(canv, _doc):
        if not payment["is_paid"]:
            return
        canv.saveState()
        try:
            canv.setFillAlpha(0.08)
            canv.setStrokeAlpha(0.2)
        except Exception:
            pass
        stamp_color = colors.HexColor("#1F3554")
        canv.setStrokeColor(stamp_color)
        canv.setFillColor(stamp_color)
        canv.setLineWidth(2)
        cx = page_width / 2
        cy = page_height / 2
        canv.translate(cx, cy)
        canv.rotate(18)
        outer_w = min(3.45 * inch, page_width - 0.55 * inch)
        outer_h = 1.95 * inch
        inner_w = outer_w - 0.22 * inch
        inner_h = outer_h - 0.22 * inch
        canv.ellipse(-outer_w/2, -outer_h/2, outer_w/2, outer_h/2, stroke=1, fill=0)
        canv.ellipse(-inner_w/2, -inner_h/2, inner_w/2, inner_h/2, stroke=1, fill=0)
        canv.setFont("Helvetica-Bold", 28)
        canv.drawCentredString(0, -5, "PAID")
        canv.setFont("Helvetica-Bold", 11)
        canv.drawCentredString(0, outer_h/2 - 18, "THANK YOU")
        canv.drawCentredString(0, -outer_h/2 + 10, "THANK YOU")
        canv.restoreState()

    doc.build(story, onFirstPage=draw_paid_watermark, onLaterPages=draw_paid_watermark)
    return buffer.getvalue()



@st.cache_data(ttl=60, show_spinner=False)
def build_invoice_print_html(order: dict) -> str:
    """Build a compact, print-friendly HTML invoice for direct browser printing."""
    payment = payment_details_for_invoice(order)
    items_html = "".join(
        f"""
        <tr>
          <td>{escape(str(item['dish']))}</td>
          <td class="num">{escape(str(item.get('quantity_label') or item['qty']))}</td>
          <td class="num">{escape(money(item['price']))}</td>
          <td class="num">{escape(money(item['line_total']))}</td>
        </tr>
        """
        for item in order["items"]
    )

    adjustments = ""
    if float(order.get("delivery_fee") or 0):
        adjustments += f'<div><span>Delivery</span><span>{escape(money(order["delivery_fee"]))}</span></div>'
    if float(order.get("discount") or 0):
        adjustments += f'<div><span>Discount</span><span>−{escape(money(order["discount"]))}</span></div>'
    if float(order.get("tax_amount") or 0):
        tax_label = f'Tax ({float(order.get("tax_percent") or 0):g}%)'
        adjustments += f'<div><span>{escape(tax_label)}</span><span>{escape(money(order["tax_amount"]))}</span></div>'

    customer_bits = []
    if order.get("customer"):
        customer_label = escape(str(order["customer"]))
        code = str(order.get("customer_code") or "").strip()
        if code:
            customer_label += f' <strong>({escape(code)})</strong>'
        customer_bits.append(f'<strong>{customer_label}</strong>')
    if order.get("phone"):
        customer_bits.append(escape(str(order["phone"])))
    if order.get("address"):
        customer_bits.append(escape(str(order["address"])))
    customer_html = "<br>".join(customer_bits)

    source_bits = []
    if order.get("order_source"):
        source_bits.append(f'Source: {escape(str(order["order_source"]))}')
    if order.get("order_taker"):
        source_bits.append(f'Taken by: {escape(str(order["order_taker"]))}')
    source_html = "<br>".join(source_bits)

    contact = "<br>".join(escape(x) for x in [kitchen_address(), BUSINESS_PHONE] if x)
    delivery_parts = []
    if order.get("delivery_date"):
        try:
            delivery_parts.append(date.fromisoformat(str(order["delivery_date"])).strftime("%A, %B %d, %Y"))
        except Exception:
            delivery_parts.append(str(order["delivery_date"]))
    if order.get("delivery_time"):
        rawt = str(order["delivery_time"])[:5]
        try:
            delivery_parts.append(datetime.strptime(rawt, "%H:%M").strftime("%I:%M %p").lstrip("0"))
        except Exception:
            delivery_parts.append(rawt)
    delivery_html = ""
    if delivery_parts:
        delivery_html = f'<div class="delivery"><strong>DELIVERY: {escape(" | ".join(delivery_parts))}</strong></div>'
    notes_html = ""
    if order.get("notes"):
        notes_html = f'<div class="notes"><strong>ORDER NOTES: {escape(str(order["notes"]))}</strong></div>'
    payment_html = ""
    if payment["is_paid"]:
        payment_bits = ['<div><span><strong>Payment status</strong></span><span><strong>PAID</strong></span></div>']
        if payment["method"]:
            payment_bits.append(f'<div><span>Method</span><span>{escape(payment["method"])}</span></div>')
        if payment["receiver"]:
            payment_bits.append(f'<div><span>Received by</span><span>{escape(payment["receiver"])}</span></div>')
        if payment["paid_at"]:
            payment_bits.append(f'<div><span>Paid at</span><span>{escape(payment["paid_at"])}</span></div>')
        payment_html = f'<div class="payment-box">{"".join(payment_bits)}</div>'
    watermark_html = '<div class="watermark" aria-hidden="true"><div class="stamp"><div class="thank top">THANK YOU</div><div class="paid">PAID</div><div class="thank bottom">THANK YOU</div></div></div>' if payment["is_paid"] else ""

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Invoice {escape(str(order['invoice_number']))}</title>
<style>
  @page {{ margin: 8mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    color: #111; background: #fff; margin: 0; padding: 0;
    font-size: 11px; line-height: 1.35;
  }}
  .invoice {{ width: 135mm; max-width: 100%; margin: 0 auto; position: relative; }}
  .watermark {{ position:absolute; inset:0; display:flex; align-items:center; justify-content:center; pointer-events:none; z-index:0; }}
  .stamp {{ width:92mm; height:52mm; border:3px solid rgba(31,53,84,.24); border-radius:999px; transform:rotate(-18deg); display:flex; align-items:center; justify-content:center; position:relative; color:rgba(31,53,84,.24); }}
  .stamp::after {{ content:''; position:absolute; inset:5mm; border:2px solid rgba(31,53,84,.20); border-radius:999px; }}
  .stamp .paid {{ font-size:24px; font-weight:800; letter-spacing:.08em; position:relative; z-index:1; }}
  .stamp .thank {{ position:absolute; font-size:11px; font-weight:700; letter-spacing:.2em; }}
  .stamp .top {{ top:7px; }}
  .stamp .bottom {{ bottom:7px; }}
  .header, .divider, .details, .delivery, table, .totals, .payment-box, .notes, .footer {{ position: relative; z-index: 1; }}
  .header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }}
  .business {{ font-size:18px; font-weight:700; }}
  .muted {{ color:#666; font-size:10px; }}
  .invoice-id {{ text-align:right; }}
  .invoice-id .label {{ font-size:15px; font-weight:700; letter-spacing:.04em; }}
  .divider {{ border-top:1px solid #bbb; margin:8px 0; }}
  .details {{ display:flex; justify-content:space-between; gap:14px; }}
  .details > div:last-child {{ text-align:right; }}
  .delivery {{ margin:8px 0; padding:7px 8px; border:1px solid #888; background:#f4f4f4; font-size:13px; }}
  table {{ width:100%; border-collapse:collapse; margin-top:8px; }}
  th {{ background:#f2f2f2; font-weight:700; border-bottom:1px solid #aaa; }}
  th, td {{ padding:5px 4px; text-align:left; vertical-align:top; }}
  td {{ border-bottom:1px solid #e2e2e2; }}
  .num {{ text-align:right; white-space:nowrap; }}
  .totals {{ width:48%; margin:8px 0 0 auto; }}
  .totals div {{ display:flex; justify-content:space-between; padding:2px 0; }}
  .totals .grand {{ border-top:1px solid #777; margin-top:3px; padding-top:5px; font-size:14px; font-weight:700; }}
  .payment-box {{ margin:8px 0 0 auto; width:56%; border:1px solid #3f7a4d; background:#f5faf5; padding:6px 8px; font-size:10px; }}
  .payment-box div {{ display:flex; justify-content:space-between; gap:10px; padding:1px 0; }}
  .notes {{ margin-top:8px; padding:6px 8px; border:1px solid #bbb; background:#f7f7f7; font-size:11px; font-weight:700; }}
  .footer {{ margin-top:9px; text-align:center; color:#666; font-size:9px; }}
  @media print {{
    .invoice {{ width:100%; }}
  }}
</style>
</head>
<body>
  <div class="invoice">
    {watermark_html}
    <div class="header">
      <div>
        <div class="business">{escape(BUSINESS_NAME)}</div>
        <div class="muted">{contact}</div>
      </div>
      <div class="invoice-id">
        <div class="label">INVOICE</div>
        <div>#{escape(str(order['invoice_number']))}</div>
        <div class="muted">{escape(str(order['date']))}</div>
      </div>
    </div>
    <div class="divider"></div>
    <div class="details">
      <div>{customer_html}</div>
      <div class="muted">{source_html}</div>
    </div>
    {delivery_html}
    <table>
      <thead><tr><th>Item</th><th class="num">Qty</th><th class="num">Unit</th><th class="num">Amount</th></tr></thead>
      <tbody>{items_html}</tbody>
    </table>
    <div class="totals">
      <div><span>Subtotal</span><span>{escape(money(order['subtotal']))}</span></div>
      {adjustments}
      <div class="grand"><span>Total</span><span>{escape(money(order['total']))}</span></div>
    </div>
    {payment_html}
    {notes_html}
    <div class="footer">Thank you for your order.</div>
  </div>
</body>
</html>"""


def render_print_button(order: dict, label: str = "🖨️ Print invoice") -> None:
    """Render a browser-native print button without downloading the PDF first."""
    printable = build_invoice_print_html(order)
    payload = json.dumps(printable)
    button_label = json.dumps(label)
    components.html(
        f"""
        <style>
          html, body {{ margin:0 !important; padding:0 !important; overflow:hidden; }}
        </style>
        <div style="margin:0;padding:0;color-scheme:light dark;">
          <button id="printInvoice" type="button" style="
            width:100%; height:40px; min-height:40px; border-radius:8px;
            border:1px solid GrayText; background:transparent; color:CanvasText;
            font:600 14px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
            cursor:pointer; padding:8px 12px;">
          </button>
          <div id="printMessage" style="font:12px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:GrayText;margin-top:4px;"></div>
        </div>
        <script>
          const btn = document.getElementById('printInvoice');
          const msg = document.getElementById('printMessage');
          btn.textContent = {button_label};
          const invoiceHtml = {payload};
          btn.addEventListener('click', () => {{
            const w = window.open('', '_blank');
            if (!w) {{
              msg.textContent = 'Allow pop-ups for this site to print directly.';
              return;
            }}
            w.document.open();
            w.document.write(invoiceHtml);
            w.document.close();
            w.focus();
            setTimeout(() => {{
              try {{ w.print(); }} catch (e) {{ msg.textContent = 'Could not open the print dialog.'; }}
            }}, 250);
          }});
        </script>
        """,
        height=40,
        scrolling=False,
    )


@st.cache_data(ttl=20, show_spinner=False)
def fetch_order_for_pdf(order_id: int) -> dict:
    db = get_db()
    row = db.table("orders").select("*").eq("id", order_id).single().execute().data
    items = db.table("order_items").select("dish,qty,quantity_label,unit_price,line_total").eq("order_id", order_id).order("id").execute().data or []
    created = local_datetime(row["created_at"])
    return {
        "invoice_number": row["invoice_number"], "date": created.strftime("%B %d, %Y %I:%M %p"),
        "order_source": row.get("order_source"), "order_taker": row.get("order_taker"), "customer": row.get("customer"),
        "customer_code": row.get("customer_code"), "phone": row.get("phone"), "address": row.get("address"), "notes": row.get("notes"),
        "delivery_date": row.get("delivery_date"), "delivery_time": row.get("delivery_time"),
        "payment_status": row.get("payment_status"), "payment_method": row.get("payment_method"),
        "payment_received_by": row.get("payment_received_by"), "paid_at": row.get("paid_at"),
        "items": [{"dish": i["dish"], "qty": float(i["qty"]), "quantity_label": i.get("quantity_label") or str(i["qty"]),
                   "price": float(i["unit_price"]), "line_total": float(i["line_total"])} for i in items],
        "subtotal": float(row["subtotal"]), "delivery_fee": float(row["delivery_fee"]), "discount": float(row["discount"]),
        "tax_percent": float(row["tax_percent"]), "tax_amount": float(row["tax_amount"]), "total": float(row["total"]),
    }


def create_staff_order(order_taker, customer, phone, address, notes, delivery_date, delivery_time, cart, delivery_fee, discount, tax_percent):
    payload = [{"menu_item_id": int(i["menu_item_id"]), "menu_option_id": int(i["option_id"]) if i.get("option_id") is not None else None, "qty": float(i["qty"]), "quantity_label": i.get("quantity_label") or str(i["qty"])} for i in cart]
    r = get_db().rpc("create_kitchen_order", {"p_order_taker": order_taker or None, "p_customer": customer or None,
        "p_phone": phone or None, "p_address": address or None, "p_notes": notes or None, "p_items": payload,
        "p_delivery_fee": float(delivery_fee), "p_discount": float(discount), "p_tax_percent": float(tax_percent)}).execute()
    if not r.data: raise RuntimeError("Supabase did not return the newly created order.")
    created = r.data[0] if isinstance(r.data, list) else r.data
    code = resolve_customer_code(customer, phone) if (customer or "").strip() else ""
    get_db().table("orders").update({
        "customer_code": code or None,
        "delivery_date": delivery_date.isoformat() if delivery_date else None,
        "delivery_time": delivery_time.strftime("%H:%M:%S") if delivery_time else None,
    }).eq("id", int(created["order_id"])).execute()
    return created


def update_order_details(order_id: int, customer: str, phone: str, delivery_date_value: date | None, delivery_time_value: time | None) -> None:
    code = resolve_customer_code(customer, phone) if (customer or "").strip() else ""
    get_db().table("orders").update({
        "customer": customer.strip() or None,
        "phone": phone.strip() or None,
        "customer_code": code or None,
        "delivery_date": delivery_date_value.isoformat() if delivery_date_value else None,
        "delivery_time": delivery_time_value.strftime("%H:%M:%S") if delivery_time_value else None,
    }).eq("id", int(order_id)).execute()
    fetch_order_for_pdf.clear()
    build_invoice_pdf.clear()
    build_invoice_print_html.clear()
    load_recent_orders.clear()


def invoice_filename(order: dict) -> str:
    code = str(order.get("customer_code") or "").strip()
    safe = "".join(ch for ch in code if ch.isalnum() or ch in ("-", "_")).strip("-_")
    base = str(order["invoice_number"])
    return f"{base}_{safe}.pdf" if safe else f"{base}.pdf"


def create_public_order(customer, phone, address, notes, cart):
    payload = [{"menu_option_id": int(i["option_id"]), "qty": float(i["qty"]), "quantity_label": i.get("quantity_label") or str(i["qty"])} for i in cart]
    r = get_db().rpc("create_public_order", {"p_customer": customer, "p_phone": phone, "p_address": address or None,
        "p_notes": notes or None, "p_items": payload}).execute()
    if not r.data: raise RuntimeError("Supabase did not return the newly created order.")
    created = r.data[0] if isinstance(r.data, list) else r.data
    code = resolve_customer_code(customer, phone) if (customer or "").strip() else ""
    get_db().table("orders").update({"customer_code": code or None}).eq("id", int(created["order_id"])).execute()
    return created


def update_order_payment(order_id, status, method, receiver):
    r = get_db().rpc("update_order_payment", {"p_order_id": int(order_id), "p_payment_status": status,
        "p_payment_method": method, "p_received_by": receiver}).execute()
    fetch_order_for_pdf.clear()
    build_invoice_pdf.clear()
    build_invoice_print_html.clear()
    load_paid_orders_for_statements.clear()
    return r.data[0] if isinstance(r.data, list) and r.data else r.data


def update_order_workflow(order_id, status):
    r = get_db().rpc("update_order_workflow", {"p_order_id": int(order_id), "p_order_status": status,
        "p_assigned_to": None}).execute()
    return r.data[0] if isinstance(r.data, list) and r.data else r.data


@st.cache_data(ttl=15, show_spinner=False)
def load_expenses() -> pd.DataFrame:
    response = (
        get_db().table("expenses")
        .select("id,category,expense_by,expense_date,description,amount,wage_per_hour,hours,reimbursed,reimbursed_date,paid_by,created_at")
        .order("expense_date", desc=True).order("id", desc=True).execute()
    )
    df = pd.DataFrame(response.data or [])
    if df.empty:
        return pd.DataFrame(columns=["id","category","expense_by","expense_date","description","amount","wage_per_hour","hours","reimbursed","reimbursed_date","paid_by","created_at"])
    for col in ["amount","wage_per_hour","hours"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def save_expense(category: str, expense_by: str, expense_date_value: date, description: str,
                 amount: float, wage_per_hour: float | None, hours: float | None,
                 settled: bool, settled_date: date | None, paid_by: str | None) -> None:
    payload = {
        "category": category,
        "expense_by": expense_by,
        "expense_date": expense_date_value.isoformat(),
        "description": description.strip() or None,
        "amount": float(amount),
        "wage_per_hour": float(wage_per_hour) if wage_per_hour is not None else None,
        "hours": float(hours) if hours is not None else None,
        "reimbursed": bool(settled),
        "reimbursed_date": settled_date.isoformat() if settled and settled_date else None,
        "paid_by": paid_by if settled else None,
    }
    get_db().table("expenses").insert(payload).execute()
    load_expenses.clear()


def settle_expense(expense_id: int, settled_date: date, paid_by: str) -> None:
    get_db().table("expenses").update({
        "reimbursed": True,
        "reimbursed_date": settled_date.isoformat(),
        "paid_by": paid_by,
    }).eq("id", int(expense_id)).execute()
    load_expenses.clear()


@st.cache_data(ttl=15, show_spinner=False)
def load_paid_orders_for_statements() -> pd.DataFrame:
    response = (
        get_db().table("orders")
        .select("id,invoice_number,customer,total,payment_method,payment_received_by,paid_at,payment_status")
        .eq("payment_status", "Paid")
        .order("paid_at", desc=True).execute()
    )
    df = pd.DataFrame(response.data or [])
    if df.empty:
        return pd.DataFrame(columns=["id","invoice_number","customer","total","payment_method","payment_received_by","paid_at","payment_status"])
    df["total"] = pd.to_numeric(df["total"], errors="coerce").fillna(0)
    return df


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return start, next_month - timedelta(days=1)


def monthly_manager_statement(year: int, month: int, managers_list: list[str]) -> dict:
    start, end = month_bounds(year, month)
    expenses = load_expenses().copy()
    orders = load_paid_orders_for_statements().copy()

    if not expenses.empty:
        expenses["expense_date_parsed"] = pd.to_datetime(expenses["expense_date"], errors="coerce").dt.date
        expenses["reimbursed_date_parsed"] = pd.to_datetime(expenses["reimbursed_date"], errors="coerce").dt.date
    if not orders.empty:
        orders["paid_local"] = orders["paid_at"].apply(lambda x: local_datetime(x) if pd.notna(x) and x else None)
        orders["paid_date"] = orders["paid_local"].apply(lambda x: x.date() if x else None)

    names = list(dict.fromkeys([m for m in managers_list if m]))
    for source_col, df in [("expense_by", expenses), ("paid_by", expenses), ("payment_received_by", orders)]:
        if not df.empty and source_col in df.columns:
            for name in df[source_col].dropna().astype(str):
                if name.strip() and name.strip() not in names:
                    names.append(name.strip())

    result = {"start": start, "end": end, "managers": []}
    for name in names:
        if orders.empty:
            payments = orders.copy()
        else:
            payments = orders[(orders["payment_received_by"].fillna("").astype(str) == name) & orders["paid_date"].apply(lambda d: d is not None and start <= d <= end)].copy()
        if expenses.empty:
            incurred = expenses.copy(); received = expenses.copy(); paid = expenses.copy(); outstanding = expenses.copy()
        else:
            incurred = expenses[(expenses["expense_by"].fillna("").astype(str) == name) & expenses["expense_date_parsed"].apply(lambda d: d is not None and start <= d <= end)].copy()
            received = expenses[(expenses["expense_by"].fillna("").astype(str) == name) & (expenses["reimbursed"] == True) & expenses["reimbursed_date_parsed"].apply(lambda d: d is not None and start <= d <= end)].copy()
            paid = expenses[(expenses["paid_by"].fillna("").astype(str) == name) & (expenses["reimbursed"] == True) & expenses["reimbursed_date_parsed"].apply(lambda d: d is not None and start <= d <= end)].copy()
            outstanding = expenses[(expenses["expense_by"].fillna("").astype(str) == name) & expenses["expense_date_parsed"].apply(lambda d: d is not None and d <= end) & expenses.apply(lambda r: (not bool(r.get("reimbursed"))) or (r.get("reimbursed_date_parsed") is not None and r.get("reimbursed_date_parsed") > end), axis=1)].copy()

        result["managers"].append({
            "name": name,
            "payments": payments,
            "expenses": incurred,
            "settlements_received": received,
            "settlements_paid": paid,
            "outstanding": outstanding,
            "payments_total": float(payments["total"].sum()) if not payments.empty else 0.0,
            "expenses_total": float(incurred["amount"].sum()) if not incurred.empty else 0.0,
            "settlements_received_total": float(received["amount"].sum()) if not received.empty else 0.0,
            "settlements_paid_total": float(paid["amount"].sum()) if not paid.empty else 0.0,
            "outstanding_total": float(outstanding["amount"].sum()) if not outstanding.empty else 0.0,
        })
    return result


def build_monthly_statement_csv(statement: dict) -> bytes:
    """Build a manager-grouped monthly cash-flow statement as UTF-8 CSV."""
    output = StringIO()
    writer = csv.writer(output)
    month_label = statement["start"].strftime("%B %Y")

    writer.writerow([BUSINESS_NAME])
    writer.writerow(["Monthly statement", month_label])
    writer.writerow([])
    writer.writerow([
        "Manager", "Entry type", "Date", "Reference / category", "Details",
        "Income", "Expense", "Settlement / transfer", "Status / counterparty"
    ])

    total_income = 0.0
    total_expense = 0.0

    for mgr in statement["managers"]:
        name = mgr["name"]

        if not mgr["payments"].empty:
            for _, row in mgr["payments"].iterrows():
                paid_dt = row.get("paid_local")
                paid_date = paid_dt.strftime("%m/%d/%Y") if paid_dt else ""
                amount = float(row.get("total") or 0)
                total_income += amount
                reference = str(row.get("invoice_number") or "")
                customer = str(row.get("customer") or "")
                method = str(row.get("payment_method") or "")
                writer.writerow([name, "Customer payment received", paid_date, reference, customer, f"{amount:.2f}", "", "", method])

        if not mgr["expenses"].empty:
            for _, row in mgr["expenses"].iterrows():
                amount = float(row.get("amount") or 0)
                total_expense += amount
                status = "Paid / settled" if bool(row.get("reimbursed")) else "Outstanding"
                paid_by = str(row.get("paid_by") or "")
                if paid_by:
                    status += f"; paid by {paid_by}"
                details = str(row.get("description") or "")
                if str(row.get("category") or "") == "Salary":
                    wage = float(row.get("wage_per_hour") or 0)
                    hours = float(row.get("hours") or 0)
                    salary_detail = f"{hours:g} hr × {CURRENCY}{wage:.2f}/hr"
                    details = f"{salary_detail}; {details}" if details else salary_detail
                writer.writerow([name, "Expense incurred", str(row.get("expense_date") or ""), str(row.get("category") or ""), details, "", f"{amount:.2f}", "", status])

        if not mgr["settlements_received"].empty:
            for _, row in mgr["settlements_received"].iterrows():
                amount = float(row.get("amount") or 0)
                writer.writerow([
                    name, "Expense / salary settlement received", str(row.get("reimbursed_date") or ""),
                    str(row.get("category") or ""), str(row.get("description") or ""), "", "", f"{amount:.2f}",
                    f"Received from {str(row.get('paid_by') or '')}".strip()
                ])

        if not mgr["settlements_paid"].empty:
            for _, row in mgr["settlements_paid"].iterrows():
                amount = float(row.get("amount") or 0)
                recipient = str(row.get("expense_by") or "")
                writer.writerow([
                    name, "Settlement paid", str(row.get("reimbursed_date") or ""),
                    str(row.get("category") or ""), str(row.get("description") or ""), "", "", f"{amount:.2f}",
                    f"Paid to {recipient}" if recipient else ""
                ])

    writer.writerow([])
    writer.writerow(["TOTAL", "Monthly totals", "", "", "", f"{total_income:.2f}", f"{total_expense:.2f}", "", ""])
    return output.getvalue().encode("utf-8-sig")


def cart_item_is_piece(item: dict) -> bool:
    return str(item.get("option") or "").strip().casefold() == "piece"



def cart_quantity_label(item: dict, qty: float) -> str:
    option = str(item.get("option") or "").strip()
    if cart_item_is_piece(item):
        q = int(round(qty))
        return f"{q} piece" if q == 1 else f"{q} pieces"
    return option if abs(qty - 1.0) < 1e-9 else f"{qty:g} × {option}"


def adjust_public_cart_item(index: int, delta: float) -> None:
    item = st.session_state.public_cart[index]
    minimum = float(item.get("min_order_qty", 1) or 1) if cart_item_is_piece(item) else 1.0
    current = float(item.get("qty", minimum))
    new_qty = max(minimum, current + delta)
    item["qty"] = new_qty
    item["quantity_label"] = cart_quantity_label(item, new_qty)
    item["line_total"] = new_qty * float(item["price"])


def public_cart_item_name(item: dict) -> str:
    option = str(item.get("option") or "").strip()
    name = str(item["dish"])
    if option and option.casefold() != "standard":
        name = f"{name} — {option}"
    return name


@st.fragment(run_every="5s")
def manager_notification_center() -> None:
    """Small polling fragment so the manager sees new online orders without reloading the page."""
    try:
        pending = load_new_online_orders()
    except Exception as exc:
        st.caption(f"Notifications unavailable: {exc}")
        return

    count = len(pending)
    if count:
        # Add a small red status dot to the keyed bell button.
        st.markdown(
            """
            <style>
            .st-key-manager_notification_bell button { position: relative; }
            .st-key-manager_notification_bell button::after {
                content: ''; position: absolute; width: .62rem; height: .62rem;
                border-radius: 50%; background: #ff4b4b; top: .28rem; right: .35rem;
                border: 2px solid var(--background-color, transparent);
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

    label = f"🔔 {count}" if count else "🔔"
    if st.button(label, key="manager_notification_bell", help=f"{count} new online order(s)" if count else "No new online orders", use_container_width=True):
        st.session_state.show_manager_notifications = not st.session_state.get("show_manager_notifications", False)

    if st.session_state.get("show_manager_notifications", False):
        if not pending:
            st.caption("No new online orders.")
        else:
            st.markdown(f"**{count} new online order{'s' if count != 1 else ''}**")
            for order in pending[:8]:
                customer = str(order.get("customer") or "Customer")
                invoice = str(order.get("invoice_number") or "")
                total = money(float(order.get("total") or 0))
                when = relative_time(order.get("created_at"))
                st.markdown(
                    f"<div style='padding:.25rem 0;border-bottom:1px solid rgba(128,128,128,.18)'>"
                    f"<b>{escape(invoice)}</b> · {escape(customer)} · <b>{escape(total)}</b><br>"
                    f"<span style='opacity:.7;font-size:.86rem'>{escape(when)}</span></div>",
                    unsafe_allow_html=True,
                )
            if count > 8:
                st.caption(f"+ {count - 8} more new orders")
            st.caption("Open Order history to review or confirm them. The badge clears as orders leave New status.")


if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    st.title(f"🍽️ {BUSINESS_NAME} Orders")
    st.error("Supabase credentials are not configured.")
    st.stop()

for key, default in [("public_cart", []), ("staff_cart", []), ("public_confirmation", None), ("staff_invoice", None), ("manager_authenticated", False), ("show_manager_notifications", False)]:
    if key not in st.session_state:
        st.session_state[key] = default

st.title(f"🍽️ {BUSINESS_NAME}")
st.caption("Browse the menu and place an order online, or sign in to the manager area.")
app_section = st.radio(
    "App section",
    ["🍽️ Menu & Order", "🔐 Manager"],
    horizontal=True,
    label_visibility="collapsed",
    key="app_section",
)

# Load only the data needed by the visible section. Streamlit tabs execute hidden
# content too; this lazy navigation avoids unnecessary database work on reruns.
menu = pd.DataFrame()
public_menu = pd.DataFrame()
managers: list[str] = []
try:
    if app_section == "🍽️ Menu & Order":
        public_menu = load_public_menu()
    elif st.session_state.manager_authenticated or not APP_PASSWORD:
        menu = load_menu()
        public_menu = load_public_menu()
        managers = load_managers()
except Exception as exc:
    st.error(f"Could not connect to the ordering database: {exc}")
    st.stop()

if app_section == "🍽️ Menu & Order":
    render_customer_announcements()
    if public_menu.empty:
        st.info("The online menu is not available yet.")
    else:
        categories = sorted(public_menu["category"].unique().tolist(), key=str.casefold)

        st.subheader("Browse menu")
        st.caption("Current dishes and prices")
        for menu_category in categories:
            category_df = public_menu[public_menu["category"] == menu_category].copy()
            with st.expander(str(menu_category), expanded=False):
                compact_rows = []
                for menu_dish in sorted(category_df["dish"].unique().tolist(), key=str.casefold):
                    dish_options = category_df[category_df["dish"] == menu_dish].sort_values(["sort_order", "price"])
                    option_parts = []
                    for _, menu_option in dish_options.iterrows():
                        label = str(menu_option["option"]).strip()
                        price_text = money(float(menu_option["price"]))
                        if label.casefold() == "standard":
                            mode = str(menu_option.get("sale_mode") or "piece").casefold()
                            if mode == "tray": option_parts.append(f"{escape(price_text)} / tray")
                            elif mode == "piece": option_parts.append(f"{escape(price_text)} / piece")
                            else: option_parts.append(escape(price_text))
                        else:
                            option_parts.append(f"{escape(label)}: {escape(price_text)}")
                    compact_rows.append(
                        "<div style='display:flex;justify-content:space-between;align-items:baseline;"
                        "gap:1rem;padding:.16rem 0;line-height:1.35'>"
                        f"<span style='font-weight:600'>{escape(str(menu_dish))}</span>"
                        f"<span style='text-align:right;white-space:nowrap'>{' · '.join(option_parts)}</span>"
                        "</div>"
                    )
                st.markdown("".join(compact_rows), unsafe_allow_html=True)

        st.subheader("Build your order")
        category = st.selectbox("Category", categories, key="public_category")
        cat_df = public_menu[public_menu["category"] == category].copy()
        dishes = sorted(cat_df["dish"].unique().tolist(), key=str.casefold)
        dish = st.selectbox("Dish", dishes, key="public_dish")
        dish_df = cat_df[cat_df["dish"] == dish].sort_values(["sort_order", "price"])
        option_ids = dish_df["option_id"].astype(int).tolist()
        if len(option_ids) > 1:
            option_id = st.selectbox("How would you like it?", option_ids,
                format_func=lambda oid: f"{dish_df.loc[dish_df['option_id']==oid, 'option'].iloc[0]} — {money(dish_df.loc[dish_df['option_id']==oid, 'price'].iloc[0])}",
                key="public_option")
        else:
            option_id = option_ids[0]
        qcol, acol = st.columns([1.2,2])
        selected = dish_df.loc[dish_df["option_id"] == option_id].iloc[0]
        option_label = str(selected["option"]).strip()
        min_order_qty = float(selected.get("min_order_qty") or 1)
        with qcol:
            if option_label.casefold() == "piece":
                min_piece = max(1, int(round(min_order_qty)))
                qty = float(st.number_input("Quantity", min_value=min_piece, max_value=100, value=min_piece, step=1, key="public_qty"))
                quantity_label = f"{int(qty)} piece" if int(qty) == 1 else f"{int(qty)} pieces"
                st.caption(f"Minimum order: {min_piece} piece{'s' if min_piece != 1 else ''}")
            else:
                qty = 1.0
                quantity_label = option_label
                st.caption(f"Selected: {option_label} · {money(float(selected['price']))}")
        with acol:
            st.write("")
            st.write("")
            if st.button("Add to cart", type="primary", use_container_width=True):
                st.session_state.public_cart.append({"option_id": int(option_id), "dish": dish,
                    "category": str(category), "option": str(selected["option"]),
                    "min_order_qty": min_order_qty, "qty": float(qty),
                    "quantity_label": quantity_label, "price": float(selected["price"]),
                    "line_total": float(qty) * float(selected["price"])})
                st.session_state.public_confirmation = None
                st.rerun()

        st.markdown("### Your cart")
        if not st.session_state.public_cart:
            st.info("Your cart is empty.")
        else:
            # Desktop cart: table-like layout. Hidden automatically on narrow screens.
            with st.container(key="cart_desktop"):
                header = st.columns([3.4, 2.6, 1.5, 1.5, 0.7])
                header[0].markdown("**Item**")
                header[1].markdown("**Qty**")
                header[2].markdown("**Unit**")
                header[3].markdown("**Total**")
                header[4].markdown("**Remove**")

                for idx, item in enumerate(st.session_state.public_cart):
                    item_name = public_cart_item_name(item)
                    is_piece = cart_item_is_piece(item)
                    step = 1.0
                    minimum = float(item.get("min_order_qty", 1) or 1) if is_piece else 1.0
                    qty_value = float(item.get("qty", minimum))

                    row = st.columns([3.4, 2.6, 1.5, 1.5, 0.7], vertical_alignment="center")
                    row[0].markdown(f"**{escape(item_name)}**")

                    with row[1]:
                        minus_col, qty_col, plus_col = st.columns([1, 1.6, 1])
                        if minus_col.button("−", key=f"desktop_minus_{idx}",
                                            disabled=qty_value <= minimum + 1e-9,
                                            use_container_width=True):
                            adjust_public_cart_item(idx, -step)
                            st.rerun()
                        display_qty = str(item.get("quantity_label") or cart_quantity_label(item, qty_value))
                        qty_col.markdown(
                            f"<div style='text-align:center;white-space:nowrap;padding-top:.45rem'>{escape(display_qty)}</div>",
                            unsafe_allow_html=True,
                        )
                        if plus_col.button("+", key=f"desktop_plus_{idx}", use_container_width=True):
                            adjust_public_cart_item(idx, step)
                            st.rerun()

                    row[2].markdown(money(float(item["price"])))
                    row[3].markdown(f"**{money(float(item['line_total']))}**")
                    if row[4].button("×", key=f"desktop_remove_{idx}", help="Remove item", use_container_width=True):
                        st.session_state.public_cart.pop(idx)
                        st.rerun()
                    st.markdown("<hr style='margin:.2rem 0 .35rem;opacity:.18'>", unsafe_allow_html=True)

            # Mobile cart: item summary + one compact control row.
            # This avoids Streamlit stacking a five-column table vertically on phones.
            with st.container(key="cart_mobile"):
                for idx, item in enumerate(st.session_state.public_cart):
                    item_name = public_cart_item_name(item)
                    is_piece = cart_item_is_piece(item)
                    step = 1.0
                    minimum = float(item.get("min_order_qty", 1) or 1) if is_piece else 1.0
                    qty_value = float(item.get("qty", minimum))
                    display_qty = str(item.get("quantity_label") or cart_quantity_label(item, qty_value))
                    unit_note = "each" if is_piece else str(item.get("option") or "package")

                    top_left, top_right = st.columns([3.2, 1.2], vertical_alignment="center")
                    top_left.markdown(f"**{escape(item_name)}**")
                    top_right.markdown(
                        f"<div style='text-align:right;font-weight:700'>{escape(money(float(item['line_total'])))}</div>",
                        unsafe_allow_html=True,
                    )
                    st.caption(f"{money(float(item['price']))} {unit_note}")

                    minus_col, qty_col, plus_col, remove_col = st.columns([1, 1.8, 1, 1])
                    if minus_col.button("−", key=f"mobile_minus_{idx}",
                                        disabled=qty_value <= minimum + 1e-9,
                                        use_container_width=True):
                        adjust_public_cart_item(idx, -step)
                        st.rerun()
                    qty_col.markdown(
                        f"<div style='text-align:center;white-space:nowrap;padding:.58rem .1rem;font-weight:600'>{escape(display_qty)}</div>",
                        unsafe_allow_html=True,
                    )
                    if plus_col.button("+", key=f"mobile_plus_{idx}", use_container_width=True):
                        adjust_public_cart_item(idx, step)
                        st.rerun()
                    if remove_col.button("×", key=f"mobile_remove_{idx}", help="Remove item", use_container_width=True):
                        st.session_state.public_cart.pop(idx)
                        st.rerun()
                    st.markdown("<hr style='margin:.35rem 0 .55rem;opacity:.18'>", unsafe_allow_html=True)

            subtotal = sum(i["line_total"] for i in st.session_state.public_cart)
            total_left, total_right = st.columns([3, 2])
            total_left.markdown("**Cart total**")
            total_right.markdown(f"### {money(subtotal)}")
            st.caption("Final price is verified against the live menu when you submit.")
            st.markdown("### Your details")
            pc1, pc2 = st.columns(2)
            with pc1:
                customer = st.text_input("Name *", key="public_customer")
                phone = st.text_input("Phone *", key="public_phone")
            with pc2:
                address = st.text_area("Address", height=70, key="public_address")
                notes = st.text_area("Order notes", height=70, key="public_notes")
            if st.button("Place order", type="primary", use_container_width=True):
                if not customer.strip() or not phone.strip():
                    st.error("Please enter your name and phone number.")
                else:
                    try:
                        created = create_public_order(customer, phone, address, notes, st.session_state.public_cart)
                        order = fetch_order_for_pdf(int(created["order_id"]))
                        st.session_state.public_confirmation = {"number": order["invoice_number"], "total": order["total"],
                            "pdf": build_invoice_pdf(order)}
                        st.session_state.public_cart = []
                        load_recent_orders.clear()
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not place the order: {exc}")

        if st.session_state.public_confirmation:
            conf = st.session_state.public_confirmation
            st.success(f"Order {conf['number']} has been submitted. Total: {money(conf['total'])}")
            st.info("The kitchen will contact you to confirm the order.")
            st.download_button("Download order confirmation", data=conf["pdf"], file_name=f"{conf['number']}.pdf",
                               mime="application/pdf", use_container_width=True)

if app_section == "🔐 Manager":
    if not st.session_state.manager_authenticated and APP_PASSWORD:
        st.subheader("Manager sign in")
        entered = st.text_input("Manager password", type="password", key="manager_password_input")
        if st.button("Sign in", type="primary", key="manager_signin"):
            if entered == APP_PASSWORD:
                st.session_state.manager_authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    else:
        if not APP_PASSWORD:
            st.warning("APP_PASSWORD is empty, so the manager area is not protected.")
        top1, top2, top3 = st.columns([4, 1.05, 1.15], vertical_alignment="center")
        top1.subheader("Manager dashboard")
        with top2:
            manager_notification_center()
        if top3.button("Sign out", use_container_width=True):
            st.session_state.manager_authenticated = False
            st.session_state.show_manager_notifications = False
            st.rerun()

        manager_section = st.radio(
            "Manager section",
            ["Staff order", "Order history", "Menu", "Expenditure", "Announcements", "Settings"],
            horizontal=True,
            label_visibility="collapsed",
            key="manager_section",
        )

        if manager_section == "Staff order":
            if menu.empty:
                st.warning("No available menu items.")
            else:
                c1,c2 = st.columns(2)
                with c1:
                    order_taker = st.selectbox("Order taken by", managers if managers else [""], key="staff_order_taker")
                    customer = st.text_input(
                        "Customer name",
                        key="staff_customer",
                        on_change=autofill_customer_contact,
                        args=("staff_customer", "staff_phone"),
                    )
                    known_customer = existing_customer_record(customer)
                    known_code = str(known_customer.get("short_code") or "") if known_customer else ""
                    if customer.strip():
                        if known_customer:
                            saved_phone = str(known_customer.get("phone") or "").strip()
                            detail = f"Customer code: **{known_code}**"
                            if saved_phone:
                                detail += f" · Saved contact: **{saved_phone}**"
                            st.caption(detail)
                        else:
                            st.caption("Customer code will be generated automatically and the contact number will be saved when this order is saved.")
                    phone = st.text_input("Phone", key="staff_phone")
                with c2:
                    address = st.text_area("Customer address", height=68, key="staff_address")
                    notes = st.text_area("Order notes", height=68, key="staff_notes")
                d1, d2 = st.columns(2)
                today_local = datetime.now(ZoneInfo(APP_TIMEZONE)).date()
                time_options = delivery_time_options()
                delivery_date_value = d1.date_input(
                    "Delivery date",
                    value=today_local,
                    min_value=today_local,
                    max_value=today_local + timedelta(days=365),
                    format="MM/DD/YYYY",
                    key="staff_delivery_date",
                )
                delivery_time_value = d2.selectbox("Delivery time", time_options, format_func=format_delivery_time, key="staff_delivery_time")
                st.markdown("### Add dishes")
                # Manager-side order entry does not need category navigation.
                # Show every available dish in one searchable dropdown; categories
                # remain in the Menu editor and customer-facing menu.
                staff_dishes = menu.sort_values("dish", key=lambda col: col.astype(str).str.casefold()).copy()
                item_id = st.selectbox(
                    "Dish",
                    staff_dishes["id"].astype(int).tolist(),
                    format_func=lambda iid: staff_dishes.loc[staff_dishes["id"] == iid, "dish"].iloc[0],
                    key="staff_dish_all",
                )
                selected = staff_dishes.loc[staff_dishes["id"] == item_id].iloc[0]
                item_options = public_menu[public_menu["menu_item_id"] == int(item_id)].copy().sort_values(["sort_order", "price"])
                ids = item_options["option_id"].astype(int).tolist()
                if not ids:
                    st.warning("This dish has no active selling format. Update it in the Menu tab.")
                    option_id = None; qv = 0.0; ql = ""; unit_price = 0.0
                else:
                    # Keep selling format and quantity as two separate controls.
                    # Always show the option dropdown, even when only one format is available,
                    # so the manager workflow stays consistent from dish to dish.
                    option_id = st.selectbox(
                        "Option",
                        ids,
                        format_func=lambda oid: f"{item_options.loc[item_options['option_id']==oid,'option'].iloc[0]} — {money(item_options.loc[item_options['option_id']==oid,'price'].iloc[0])}",
                        key=f"staff_option_{item_id}",
                    )
                    option_row = item_options.loc[item_options["option_id"] == option_id].iloc[0]
                    option_label = str(option_row["option"]).strip()
                    unit_price = float(option_row["price"])
                    minq = float(option_row.get("min_order_qty") or 1)
                    minimum_qty = max(1, int(round(minq))) if option_label.casefold() == "piece" else 1

                    qty_key = f"staff_add_qty_{item_id}_{option_id}"
                    if qty_key not in st.session_state:
                        st.session_state[qty_key] = minimum_qty
                    # If a menu minimum was raised after this state was created, respect the new minimum.
                    st.session_state[qty_key] = max(minimum_qty, int(st.session_state[qty_key]))

                    st.markdown("**Quantity**")
                    minus_col, qty_col, plus_col = st.columns([1, 1.35, 1])

                    # Run both button actions before the number_input is instantiated.
                    # This lets the same value be changed either with −/+ or by typing.
                    if minus_col.button(
                        "−",
                        key=f"staff_add_minus_{item_id}_{option_id}",
                        disabled=int(st.session_state[qty_key]) <= minimum_qty,
                        use_container_width=True,
                    ):
                        st.session_state[qty_key] = max(minimum_qty, int(st.session_state[qty_key]) - 1)
                        st.rerun()
                    if plus_col.button(
                        "+",
                        key=f"staff_add_plus_{item_id}_{option_id}",
                        disabled=int(st.session_state[qty_key]) >= 100,
                        use_container_width=True,
                    ):
                        st.session_state[qty_key] = min(100, int(st.session_state[qty_key]) + 1)
                        st.rerun()

                    with qty_col:
                        typed_qty = st.number_input(
                            "Quantity",
                            min_value=int(minimum_qty),
                            max_value=100,
                            step=1,
                            key=qty_key,
                            label_visibility="collapsed",
                        )
                    qv = float(int(typed_qty))

                    if option_label.casefold() == "piece":
                        ql = f"{int(qv)} piece" if int(qv) == 1 else f"{int(qv)} pieces"
                        st.caption(f"Minimum order: {minimum_qty} piece{'s' if minimum_qty != 1 else ''} · {money(unit_price)} each")
                    else:
                        ql = option_label if int(qv) == 1 else f"{int(qv)} × {option_label}"
                        st.caption(f"{option_label} · {money(unit_price)} each")

                if st.button("Add to staff order", type="primary", use_container_width=True, disabled=option_id is None):
                    st.session_state.staff_cart.append({"menu_item_id": int(item_id), "option_id": int(option_id) if option_id is not None else None, "dish": str(selected["dish"]),
                        "qty": qv, "quantity_label": ql, "price": unit_price, "line_total": qv*unit_price})
                    st.session_state.staff_invoice = None; st.rerun()
                if st.session_state.staff_cart:
                    st.markdown("### Current order")
                    for i,item in enumerate(st.session_state.staff_cart):
                        a,b,c,d = st.columns([4,1.3,1.5,.7])
                        a.write(f"**{item['dish']}**"); b.write(f"× {item['quantity_label']}"); c.write(money(item["line_total"]))
                        if d.button("✕", key=f"staff_remove_{i}"):
                            st.session_state.staff_cart.pop(i); st.rerun()
                    sub = sum(i["line_total"] for i in st.session_state.staff_cart)
                    a,b,c = st.columns(3)
                    delivery = a.number_input("Delivery fee", min_value=0.0, value=0.0, step=1.0, key="staff_delivery")
                    discount = b.number_input("Discount", min_value=0.0, value=0.0, step=1.0, key="staff_discount")
                    tax = c.number_input("Tax %", min_value=0.0, value=0.0, step=.25, key="staff_tax")
                    est = max(0, sub+delivery-discount) * (1+tax/100)
                    st.markdown(f"### Estimated total: {money(est)}")
                    if st.button("Save & generate invoice", type="primary", use_container_width=True):
                        try:
                            created = create_staff_order(order_taker, customer, phone, address, notes, delivery_date_value, delivery_time_value, st.session_state.staff_cart, delivery, discount, tax)
                            order = fetch_order_for_pdf(int(created["order_id"]))
                            st.session_state.staff_invoice = {"number": order["invoice_number"], "pdf": build_invoice_pdf(order), "order": order}
                            st.session_state.staff_cart = []; load_recent_orders.clear(); st.rerun()
                        except Exception as exc:
                            st.error(f"Could not save order: {exc}")
                if st.session_state.staff_invoice:
                    inv = st.session_state.staff_invoice
                    st.success(f"Invoice {inv['number']} saved.")
                    dl_col, print_col = st.columns(2)
                    with dl_col:
                        st.download_button("Download PDF invoice", data=inv["pdf"], file_name=invoice_filename(inv["order"]), mime="application/pdf", use_container_width=True)
                    with print_col:
                        if inv.get("order"):
                            render_print_button(inv["order"])


        if manager_section == "Order history":
            h1,h2 = st.columns([3,1]); h1.subheader("Recent orders")
            if h2.button("Refresh", use_container_width=True): load_recent_orders.clear(); st.rerun()
            orders = load_recent_orders()
            if orders.empty:
                st.info("No orders yet.")
            else:
                search_orders = st.text_input("Find invoice", placeholder="Search invoice #, customer name, short code, or phone", key="history_search")
                if search_orders.strip():
                    q = search_orders.strip().casefold()
                    mask = orders.apply(lambda r: any(q in str(r.get(c) or "").casefold() for c in ["invoice_number","customer","customer_code","phone"]), axis=1)
                    filtered_orders = orders[mask].copy()
                else:
                    filtered_orders = orders.copy()
                if filtered_orders.empty:
                    st.info("No matching orders. Clear the search box to show all invoices.")
                    filtered_orders = orders.copy()
                display = filtered_orders.copy()
                display["created_at"] = display["created_at"].map(lambda x: local_datetime(x).strftime("%b %d, %Y %I:%M %p"))
                if "delivery_date" in display.columns:
                    display["delivery_date"] = display["delivery_date"].map(lambda x: date.fromisoformat(str(x)).strftime("%b %d") if pd.notna(x) and str(x) not in {"", "None"} else "-")
                if "delivery_time" in display.columns:
                    def _fmt_hist_time(x):
                        if pd.isna(x) or str(x) in {"", "None"}: return "-"
                        try: return datetime.strptime(str(x)[:5], "%H:%M").strftime("%I:%M %p").lstrip("0")
                        except Exception: return str(x)
                    display["delivery_time"] = display["delivery_time"].map(_fmt_hist_time)
                display["total"] = display["total"].map(money)
                display = display.rename(columns={"invoice_number":"Invoice","created_at":"Date","order_source":"Source","order_taker":"Taken by",
                    "customer":"Customer","customer_code":"Code","delivery_date":"Delivery date","delivery_time":"Delivery time","total":"Total","payment_status":"Payment","payment_method":"Method",
                    "payment_received_by":"Received by","order_status":"Status"})
                for col in ["Taken by","Method","Received by"]: display[col] = display[col].fillna("-")
                st.dataframe(display[["Invoice","Customer","Code","Delivery date","Delivery time","Total","Status","Payment","Method","Received by","Taken by"]],
                             use_container_width=True, hide_index=True)
                chosen = st.selectbox("Select order", filtered_orders["invoice_number"].tolist(),
                    format_func=lambda inv: f"{inv} · {filtered_orders.loc[filtered_orders['invoice_number']==inv, 'customer_code'].iloc[0] or filtered_orders.loc[filtered_orders['invoice_number']==inv, 'customer'].iloc[0] or 'Customer'}",
                    key="history_order")
                row = orders.loc[orders["invoice_number"]==chosen].iloc[0]
                st.markdown("#### Customer & delivery")
                e1,e2,e3,e4,e5 = st.columns([1.7,1.2,1.4,1.3,1])
                edit_customer_key = f"edit_customer_{row['id']}"
                edit_phone_key = f"edit_phone_{row['id']}"
                edit_customer = e1.text_input(
                    "Customer",
                    value=str(row.get("customer") or ""),
                    key=edit_customer_key,
                    on_change=autofill_customer_contact,
                    args=(edit_customer_key, edit_phone_key),
                )
                edit_phone = e2.text_input("Phone", value=str(row.get("phone") or ""), key=edit_phone_key)
                auto_code = existing_customer_code(edit_customer) or str(row.get("customer_code") or "")
                if auto_code:
                    e2.caption(f"Code: **{auto_code}**")
                today_local = datetime.now(ZoneInfo(APP_TIMEZONE)).date()
                try:
                    current_dd = date.fromisoformat(str(row.get("delivery_date"))) if row.get("delivery_date") else today_local
                except Exception:
                    current_dd = today_local
                edit_dd = e3.date_input(
                    "Delivery date",
                    value=current_dd,
                    min_value=min(current_dd, today_local - timedelta(days=365)),
                    max_value=max(current_dd, today_local + timedelta(days=365)),
                    format="MM/DD/YYYY",
                    key=f"edit_dd_{row['id']}",
                )
                time_opts = delivery_time_options()
                try:
                    raw_time = str(row.get("delivery_time") or "")[:5]
                    current_dt = datetime.strptime(raw_time, "%H:%M").time() if raw_time else time_opts[0]
                except Exception:
                    current_dt = time_opts[0]
                if current_dt not in time_opts:
                    time_opts = [current_dt] + time_opts
                edit_dt = e4.selectbox("Delivery time", time_opts, index=time_opts.index(current_dt), format_func=format_delivery_time, key=f"edit_dt_{row['id']}")
                e5.write(""); e5.write("")
                if e5.button("Save details", type="primary", use_container_width=True, key=f"save_details_{row['id']}"):
                    try:
                        update_order_details(int(row["id"]), edit_customer, edit_phone, edit_dd, edit_dt)
                        st.success("Customer and delivery details updated."); st.rerun()
                    except Exception as exc:
                        st.error(f"Could not update details: {exc}")
                st.markdown("#### Order workflow")
                statuses = ["New","Confirmed","Preparing","Ready","Delivered","Cancelled"]
                current_status = str(row.get("order_status") or "New")
                w1,w2 = st.columns([2.2,1])
                status = w1.selectbox("Order status", statuses, index=statuses.index(current_status) if current_status in statuses else 0, key=f"status_{row['id']}")
                w2.write(""); w2.write("")
                if w2.button("Save status", type="primary", use_container_width=True, key=f"save_status_{row['id']}"):
                    try:
                        update_order_workflow(int(row["id"]), status); load_recent_orders.clear(); st.success("Order updated."); st.rerun()
                    except Exception as exc: st.error(f"Could not update order: {exc}")
                st.markdown("#### Payment")
                methods = ["Cash","Zelle","Card","Venmo","Other"]
                cur_p = str(row.get("payment_status") or "Unpaid"); cur_m = str(row.get("payment_method") or "Cash")
                if cur_m not in methods: methods.append(cur_m)
                cur_r = str(row.get("payment_received_by") or (managers[0] if managers else ""))
                recv_opts = managers.copy()
                if cur_r and cur_r not in recv_opts: recv_opts.append(cur_r)
                p1,p2,p3,p4 = st.columns([1.2,1.4,1.4,1])
                pstat = p1.selectbox("Payment status", ["Unpaid","Paid"], index=1 if cur_p=="Paid" else 0, key=f"pstat_{row['id']}")
                pmethod = p2.selectbox("Payment method", methods, index=methods.index(cur_m), disabled=pstat!="Paid", key=f"pmethod_{row['id']}")
                receiver = p3.selectbox("Received by", recv_opts if recv_opts else [""], index=recv_opts.index(cur_r) if cur_r in recv_opts else 0,
                                        disabled=pstat!="Paid", key=f"receiver_{row['id']}")
                p4.write(""); p4.write("")
                if p4.button("Save payment", type="primary", use_container_width=True, key=f"savepay_{row['id']}"):
                    try:
                        update_order_payment(int(row["id"]), pstat, pmethod if pstat=="Paid" else None, receiver if pstat=="Paid" else None)
                        load_recent_orders.clear(); st.success("Payment updated."); st.rerun()
                    except Exception as exc: st.error(f"Could not update payment: {exc}")
                try:
                    old = fetch_order_for_pdf(int(row["id"])); pdf = build_invoice_pdf(old)
                    st.markdown("#### Invoice")
                    if "invoice_preview_order_id" not in st.session_state:
                        st.session_state.invoice_preview_order_id = None
                    view_col, print_col, dl_col = st.columns(3)
                    with view_col:
                        if st.button("👁️ View invoice", use_container_width=True, key=f"view_invoice_{row['id']}"):
                            st.session_state.invoice_preview_order_id = None if st.session_state.invoice_preview_order_id == int(row["id"]) else int(row["id"])
                            st.rerun()
                    with print_col:
                        render_print_button(old, label="🖨️ Print invoice")
                    with dl_col:
                        st.download_button("⬇️ Download invoice", data=pdf, file_name=invoice_filename(old), mime="application/pdf", use_container_width=True)
                    if st.session_state.invoice_preview_order_id == int(row["id"]):
                        st.caption("Invoice preview")
                        components.html(build_invoice_print_html(old), height=650, scrolling=True)
                except Exception as exc: st.warning(f"Could not prepare invoice: {exc}")

        if manager_section == "Menu":
            st.subheader("Menu management")
            st.caption("A dish can be sold in one or several formats. Select every format that applies and set its price.")

            STANDARD_FORMATS = ["Piece", "Small Box", "Box", "Half Tray", "Tray"]

            try:
                all_menu = load_all_menu_items()
            except Exception as exc:
                all_menu = pd.DataFrame(columns=["id","dish","category","price","available"])
                st.error(f"Could not load menu items: {exc}")

            category_options = sorted({str(x).strip() for x in all_menu.get("category", pd.Series(dtype=str)).dropna().tolist() if str(x).strip()})
            if not category_options:
                category_options = ["Bangla items", "Chinese", "Dessert", "Frozen"]

            with st.expander("➕ Add new dish", expanded=all_menu.empty):
                a1, a2 = st.columns([2, 1.3])
                new_dish = a1.text_input("Dish name", key="new_menu_dish")
                new_category = a2.selectbox("Category", category_options, key="new_menu_category")
                new_formats = st.multiselect(
                    "How is it sold?",
                    STANDARD_FORMATS,
                    placeholder="Select one or more",
                    key="new_menu_formats",
                )
                new_units = []
                if new_formats:
                    st.caption("Set the price only for the selected selling formats.")
                    price_cols = st.columns(2)
                    for idx, label in enumerate(new_formats):
                        with price_cols[idx % 2]:
                            price = st.number_input(
                                f"{label} price",
                                min_value=0.0,
                                value=0.0,
                                step=.5,
                                format="%.2f",
                                key=f"new_{label}_price",
                            )
                            min_qty = 1
                            if label == "Piece":
                                min_qty = st.number_input(
                                    "Minimum order (pieces)",
                                    min_value=1,
                                    value=1,
                                    step=1,
                                    key="new_piece_min",
                                )
                            new_units.append({"label": label, "price": float(price), "min_order_qty": float(min_qty)})
                else:
                    st.caption("Select one or more selling formats to enter pricing.")

                new_available = st.checkbox("Available to customers", value=True, key="new_menu_available")
                add_item = st.button("Add dish", type="primary", use_container_width=True, key="add_menu_item_button")
                if add_item:
                    if not new_dish.strip():
                        st.error("Enter a dish name.")
                    elif not new_formats:
                        st.error("Select at least one selling format.")
                    else:
                        try:
                            save_menu_item(None, new_dish, new_category, new_available, new_units)
                            st.success("Dish added.")
                            for key in ["new_menu_dish", "new_menu_formats", "new_menu_available", "new_piece_min"]:
                                st.session_state.pop(key, None)
                            for label in STANDARD_FORMATS:
                                st.session_state.pop(f"new_{label}_price", None)
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Could not add dish: {exc}")

            if all_menu.empty:
                st.info("No menu items yet.")
            else:
                summary_rows = []
                for _, mrow in all_menu.iterrows():
                    opts = [o for o in load_menu_option_details(int(mrow["id"])) if o["active"]]
                    selling = ", ".join(o["label"] for o in opts) or "—"
                    prices = " · ".join(f"{o['label']}: {money(o['price'])}" for o in opts) or "—"
                    summary_rows.append({"Category": mrow["category"], "Dish": mrow["dish"], "Selling": selling, "Prices": prices, "Available": "Yes" if bool(mrow["available"]) else "No"})
                st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

                st.markdown("#### Edit a dish")
                selected_id = st.selectbox(
                    "Select dish",
                    all_menu["id"].astype(int).tolist(),
                    format_func=lambda iid: f"{all_menu.loc[all_menu['id']==iid, 'category'].iloc[0]} · {all_menu.loc[all_menu['id']==iid, 'dish'].iloc[0]}",
                    key="menu_editor_selected_id",
                )
                selected_row = all_menu.loc[all_menu["id"] == selected_id].iloc[0]
                option_details = load_menu_option_details(int(selected_id))
                active_options = {o["label"]: o for o in option_details if o["active"]}
                selected_standard = [f for f in STANDARD_FORMATS if f in active_options]
                custom_active = [o for o in option_details if o["active"] and o["label"] not in STANDARD_FORMATS and o["label"] != "Standard"]

                e1, e2 = st.columns([2, 1.3])
                edit_dish = e1.text_input("Dish name", value=str(selected_row["dish"]), key=f"edit_menu_dish_{selected_id}")
                current_category = str(selected_row["category"] or "").strip()
                edit_category_options = category_options.copy()
                if current_category and current_category not in edit_category_options:
                    edit_category_options.append(current_category)
                    edit_category_options = sorted(edit_category_options)
                edit_category = e2.selectbox(
                    "Category",
                    edit_category_options,
                    index=edit_category_options.index(current_category) if current_category in edit_category_options else 0,
                    key=f"edit_menu_category_{selected_id}",
                )
                edit_formats = st.multiselect(
                    "How is it sold?",
                    STANDARD_FORMATS,
                    default=selected_standard,
                    key=f"edit_menu_formats_{selected_id}",
                )
                if custom_active:
                    st.caption("Existing special formats preserved: " + ", ".join(f"{o['label']} ({money(o['price'])})" for o in custom_active))
                edit_units = []
                if edit_formats:
                    st.caption("Set the price only for the selected selling formats.")
                    edit_cols = st.columns(2)
                    for idx, label in enumerate(edit_formats):
                        current = active_options.get(label, {})
                        with edit_cols[idx % 2]:
                            price = st.number_input(
                                f"{label} price",
                                min_value=0.0,
                                value=float(current.get("price", selected_row.get("price") or 0)),
                                step=.5,
                                format="%.2f",
                                key=f"edit_{selected_id}_{label}_price",
                            )
                            min_qty = 1
                            if label == "Piece":
                                min_qty = st.number_input(
                                    "Minimum order (pieces)",
                                    min_value=1,
                                    value=max(1, int(round(float(current.get("min_order_qty", 1))))),
                                    step=1,
                                    key=f"edit_{selected_id}_piece_min",
                                )
                            edit_units.append({"label": label, "price": float(price), "min_order_qty": float(min_qty)})
                edit_available = st.checkbox("Available to customers", value=bool(selected_row["available"]), key=f"edit_available_{selected_id}")
                save_item = st.button("Save changes", type="primary", use_container_width=True, key=f"save_menu_item_{selected_id}")
                if save_item:
                    if not edit_formats and not custom_active:
                        st.error("Select at least one selling format.")
                    else:
                        try:
                            save_menu_item(int(selected_id), edit_dish, edit_category, edit_available, edit_units)
                            st.success("Menu item updated.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Could not update dish: {exc}")

                st.caption("You can select multiple formats for the same dish, for example **Box + Half Tray + Tray**. Existing special formats are preserved unless we explicitly convert them later.")

        if manager_section == "Expenditure":
            st.subheader("Expenditure")
            st.caption("Record business expenses, salary, reimbursements, and monthly manager cash-flow statements.")

            # These controls intentionally live outside st.form so dependent fields
            # appear immediately when Category or the reimbursement checkbox changes.
            expense_widget_keys = [
                "expense_category", "expense_person", "expense_date_value",
                "expense_hours", "expense_amount", "expense_description", "expense_settled",
                "expense_settled_date", "expense_paid_by"
            ]
            if st.session_state.pop("_reset_expense_entry", False):
                for key in expense_widget_keys:
                    st.session_state.pop(key, None)

            x1, x2, x3 = st.columns(3)
            expense_category = x1.selectbox(
                "Expense category", ["Bazaar", "Salary", "Equipment", "Misc"],
                key="expense_category"
            )
            person_label = "Salary for" if expense_category == "Salary" else "Expense by"
            expense_person = x2.selectbox(person_label, managers if managers else [""], key="expense_person")
            expense_date_value = x3.date_input(
                "Expense date", value=datetime.now(ZoneInfo(APP_TIMEZONE)).date(),
                format="MM/DD/YYYY", key="expense_date_value"
            )

            wage = hours = None
            amount = 0.0
            if expense_category == "Salary":
                wage = float(default_hourly_salary())
                s1, s2 = st.columns([1.1, 1.4])
                s1.metric("Hourly rate", money(wage))
                s1.caption("Set in Manager → Settings")
                hours = s2.number_input(
                    "Hours", min_value=0.001, value=1.0, step=0.25, format="%.3f",
                    help="Fractions/decimals are allowed, e.g. 1.5, 2.25, 7.75 hours.",
                    key="expense_hours"
                )
                amount = round(float(wage) * float(hours), 2)
                if wage <= 0:
                    st.warning("Set the hourly salary in Settings before saving a Salary expense.")
                st.markdown(f"**Calculated salary: {money(amount)}**")
            else:
                amount = st.number_input(
                    "Amount", min_value=0.0, value=0.0, step=1.0, format="%.2f",
                    key="expense_amount"
                )

            description = st.text_input(
                "Description / note",
                placeholder="Example: Costco groceries, new pot, August kitchen hours",
                key="expense_description"
            )
            settled = st.checkbox(
                "This person has already received the payment / reimbursement",
                value=False, key="expense_settled"
            )
            settled_date = None
            paid_by = None
            if settled:
                y1, y2 = st.columns(2)
                settled_date = y1.date_input(
                    "Paid / reimbursed date",
                    value=datetime.now(ZoneInfo(APP_TIMEZONE)).date(),
                    format="MM/DD/YYYY", key="expense_settled_date"
                )
                paid_by = y2.selectbox("Paid by", managers if managers else [""], key="expense_paid_by")

            if st.button("Save expenditure", type="primary", use_container_width=True, key="save_expenditure_button"):
                if not expense_person:
                    st.error("Select the manager/person for this expense.")
                elif expense_category == "Salary" and float(wage or 0) <= 0:
                    st.error("Set the hourly salary in Settings before saving a Salary expense.")
                elif float(amount) <= 0:
                    st.error("Expense amount must be greater than zero.")
                elif settled and not paid_by:
                    st.error("Select who paid/reimbursed this expense.")
                else:
                    try:
                        save_expense(
                            expense_category, expense_person, expense_date_value, description,
                            float(amount), wage if expense_category == "Salary" else None,
                            hours if expense_category == "Salary" else None,
                            settled, settled_date, paid_by
                        )
                        st.session_state["_reset_expense_entry"] = True
                        st.success("Expenditure saved.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not save expenditure: {exc}")

            st.markdown("#### Recent expenditures")
            try:
                expense_df = load_expenses()
            except Exception as exc:
                expense_df = pd.DataFrame()
                st.error(f"Could not load expenditures: {exc}")
            if expense_df.empty:
                st.info("No expenditures recorded yet.")
            else:
                exp_display = expense_df.head(100).copy()
                exp_display["Status"] = exp_display["reimbursed"].apply(lambda x: "Paid / settled" if bool(x) else "Outstanding")
                exp_display["Amount"] = exp_display["amount"].apply(lambda x: money(x or 0))
                exp_display = exp_display.rename(columns={"expense_date":"Date","category":"Category","expense_by":"Person","description":"Details","paid_by":"Paid by","reimbursed_date":"Paid date"})
                cols=[c for c in ["Date","Category","Person","Details","Amount","Status","Paid date","Paid by"] if c in exp_display.columns]
                st.dataframe(exp_display[cols], use_container_width=True, hide_index=True)

                outstanding_df = expense_df[expense_df["reimbursed"] != True].copy()
                if not outstanding_df.empty:
                    st.markdown("#### Mark an outstanding expense as paid")
                    outstanding_ids = outstanding_df["id"].astype(int).tolist()
                    settle_id = st.selectbox(
                        "Outstanding expense",
                        outstanding_ids,
                        format_func=lambda eid: (
                            f"{outstanding_df.loc[outstanding_df['id']==eid, 'expense_date'].iloc[0]} · "
                            f"{outstanding_df.loc[outstanding_df['id']==eid, 'expense_by'].iloc[0]} · "
                            f"{outstanding_df.loc[outstanding_df['id']==eid, 'category'].iloc[0]} · "
                            f"{money(outstanding_df.loc[outstanding_df['id']==eid, 'amount'].iloc[0])}"
                        ),
                        key="settle_expense_id",
                    )
                    z1,z2,z3 = st.columns([1.4,1.4,1])
                    settle_date_value = z1.date_input("Payment date", value=datetime.now(ZoneInfo(APP_TIMEZONE)).date(), format="MM/DD/YYYY", key="settle_expense_date")
                    settle_paid_by = z2.selectbox("Paid by", managers if managers else [""], key="settle_expense_paid_by")
                    z3.write(""); z3.write("")
                    if z3.button("Mark paid", type="primary", use_container_width=True, key="settle_expense_button"):
                        try:
                            settle_expense(int(settle_id), settle_date_value, settle_paid_by)
                            st.success("Expense marked as paid / settled.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Could not settle expense: {exc}")

            st.markdown("### Monthly statement")
            now_local = datetime.now(ZoneInfo(APP_TIMEZONE))
            m1, m2 = st.columns(2)
            statement_month = m1.selectbox("Month", list(range(1,13)), index=now_local.month-1, format_func=lambda m: date(2000,m,1).strftime("%B"))
            year_choices = list(range(now_local.year - 3, now_local.year + 2))
            statement_year = m2.selectbox("Year", year_choices, index=year_choices.index(now_local.year))
            try:
                statement = monthly_manager_statement(int(statement_year), int(statement_month), managers)
                for mgr in statement["managers"]:
                    with st.expander(mgr["name"], expanded=False):
                        a,b,c,d,e = st.columns(5)
                        a.metric("Payments received", money(mgr["payments_total"]))
                        b.metric("Expenses", money(mgr["expenses_total"]))
                        c.metric("Settlements received", money(mgr["settlements_received_total"]))
                        d.metric("Settlements paid", money(mgr["settlements_paid_total"]))
                        e.metric("Outstanding", money(mgr["outstanding_total"]))

                        if not mgr["payments"].empty:
                            st.caption("Customer payments received")
                            pdsp = mgr["payments"].copy()
                            pdsp["Date"] = pdsp["paid_local"].apply(lambda x: x.strftime("%m/%d/%Y") if x else "")
                            pdsp["Amount"] = pdsp["total"].apply(money)
                            pdsp = pdsp.rename(columns={"invoice_number":"Invoice","customer":"Customer","payment_method":"Method"})
                            st.dataframe(pdsp[["Date","Invoice","Customer","Method","Amount"]], hide_index=True, use_container_width=True)
                        if not mgr["expenses"].empty:
                            st.caption("Expenses incurred")
                            edsp = mgr["expenses"].copy()
                            edsp["Amount"] = edsp["amount"].apply(money)
                            edsp["Status"] = edsp["reimbursed"].apply(lambda x: "Paid / settled" if bool(x) else "Outstanding")
                            edsp = edsp.rename(columns={"expense_date":"Date","category":"Category","description":"Details","paid_by":"Paid by","reimbursed_date":"Paid date"})
                            st.dataframe(edsp[["Date","Category","Details","Amount","Status","Paid date","Paid by"]], hide_index=True, use_container_width=True)

                overall_income = sum(float(mgr["payments_total"]) for mgr in statement["managers"])
                overall_expense = sum(float(mgr["expenses_total"]) for mgr in statement["managers"])
                st.markdown("#### Monthly totals")
                totals_display = pd.DataFrame([{
                    "Manager": "TOTAL",
                    "Income": money(overall_income),
                    "Expenses": money(overall_expense),
                }])
                st.dataframe(totals_display, hide_index=True, use_container_width=True)

                statement_csv = build_monthly_statement_csv(statement)
                filename = f"{BUSINESS_NAME.replace(' ', '_')}_statement_{statement_year}_{int(statement_month):02d}.csv"
                st.download_button(
                    "Download monthly statement CSV", data=statement_csv, file_name=filename,
                    mime="text/csv", type="primary", use_container_width=True
                )
            except Exception as exc:
                st.error(f"Could not generate monthly statement: {exc}")

        if manager_section == "Announcements":
            st.subheader("Customer announcements")
            st.caption("Active announcements appear at the top of the public Menu & Order page.")

            with st.form("new_announcement_form", clear_on_submit=True):
                a1, a2 = st.columns([2, 1])
                with a1:
                    new_title = st.text_input("Title", value="Announcement")
                with a2:
                    new_level = st.selectbox("Style", ["Info", "Important", "Warning", "Success"])
                new_message = st.text_area("Message", placeholder="Example: We are accepting Eid catering orders through Friday.", height=100)
                new_active = st.checkbox("Show to customers immediately", value=True)
                publish = st.form_submit_button("Publish announcement", type="primary", use_container_width=True)
                if publish:
                    if not new_message.strip():
                        st.error("Please enter an announcement message.")
                    else:
                        try:
                            create_announcement(new_title, new_message, new_level, new_active)
                            st.success("Announcement published.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Could not publish announcement: {exc}")

            try:
                existing_announcements = load_all_announcements()
            except Exception as exc:
                existing_announcements = []
                st.error(f"Could not load announcements: {exc}")

            if not existing_announcements:
                st.info("No announcements yet.")
            else:
                st.markdown("#### Existing announcements")
                for ann in existing_announcements:
                    ann_id = int(ann["id"])
                    updated = local_datetime(ann.get("updated_at") or ann.get("created_at")).strftime("%b %d, %Y %I:%M %p")
                    status = "Active" if ann.get("active") else "Hidden"
                    with st.expander(f"{ann.get('title') or 'Announcement'} · {status} · {updated}", expanded=False):
                        title_key = f"ann_title_{ann_id}"
                        msg_key = f"ann_message_{ann_id}"
                        level_key = f"ann_level_{ann_id}"
                        active_key = f"ann_active_{ann_id}"
                        edit_title = st.text_input("Title", value=str(ann.get("title") or "Announcement"), key=title_key)
                        levels = ["Info", "Important", "Warning", "Success"]
                        current_level = str(ann.get("level") or "Info")
                        if current_level not in levels:
                            levels.append(current_level)
                        edit_level = st.selectbox("Style", levels, index=levels.index(current_level), key=level_key)
                        edit_message = st.text_area("Message", value=str(ann.get("message") or ""), height=100, key=msg_key)
                        edit_active = st.checkbox("Visible to customers", value=bool(ann.get("active")), key=active_key)
                        if st.button("Save announcement", key=f"save_ann_{ann_id}", use_container_width=True):
                            if not edit_message.strip():
                                st.error("Announcement message cannot be empty.")
                            else:
                                try:
                                    update_announcement(ann_id, edit_title, edit_message, edit_level, edit_active)
                                    st.success("Announcement updated.")
                                    st.rerun()
                                except Exception as exc:
                                    st.error(f"Could not update announcement: {exc}")

        if manager_section == "Settings":
            st.subheader("Kitchen settings")
            current_settings = load_store_settings()

            st.markdown("#### Kitchen address")
            st.caption("The kitchen address is printed on every invoice.")
            kitchen_addr = st.text_area(
                "Kitchen address",
                value=current_settings.get("kitchen_address", ""),
                height=90,
                placeholder="Street, city, state, ZIP",
                key="settings_kitchen_address",
            )
            if st.button("Save kitchen address", use_container_width=True, key="save_kitchen_address"):
                try:
                    save_store_setting("kitchen_address", kitchen_addr)
                    st.success("Kitchen address saved.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not save kitchen address: {exc}")

            st.markdown("#### Salary settings")
            saved_hourly = default_hourly_salary()
            hourly_salary = st.number_input(
                "Default hourly salary",
                min_value=0.0,
                value=float(saved_hourly),
                step=0.5,
                format="%.2f",
                help="This saved rate is used automatically for all new Salary expenditure entries.",
                key="settings_hourly_salary",
            )
            if st.button("Save hourly salary", type="primary", use_container_width=True, key="save_hourly_salary"):
                try:
                    save_store_setting("hourly_salary", f"{float(hourly_salary):.2f}")
                    st.success("Default hourly salary saved.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not save hourly salary: {exc}")


st.divider()
st.caption(f"© {BUSINESS_NAME} · Online orders are submitted directly to the kitchen database.")
