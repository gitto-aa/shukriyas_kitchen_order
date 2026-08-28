from __future__ import annotations

from datetime import datetime
from fractions import Fraction
from html import escape
from io import BytesIO
from zoneinfo import ZoneInfo
import os
import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
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
        .select("id,dish,category,price,available")
        .eq("available", True)
        .order("category").order("dish").execute()
    )
    df = pd.DataFrame(response.data or [])
    if df.empty:
        return pd.DataFrame(columns=["id", "dish", "category", "price", "available"])
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    return df.dropna(subset=["price"]).reset_index(drop=True)


@st.cache_data(ttl=30, show_spinner=False)
def load_public_menu() -> pd.DataFrame:
    response = (
        get_db().table("menu_options")
        .select("id,menu_item_id,label,price,active,sort_order,menu!inner(id,dish,category,available)")
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
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=30, show_spinner=False)
def load_managers() -> list[str]:
    response = get_db().table("managers").select("name,active").eq("active", True).order("name").execute()
    return [str(row["name"]) for row in response.data or []]


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


@st.cache_data(ttl=10, show_spinner=False)
def load_recent_orders(limit: int = 100) -> pd.DataFrame:
    response = (
        get_db().table("orders")
        .select("id,invoice_number,created_at,order_source,order_taker,assigned_to,customer,phone,total,payment_status,payment_method,payment_received_by,paid_at,order_status")
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


def build_invoice_pdf(order: dict) -> bytes:
    """Create a compact, invoice-style PDF with minimal unused page space."""
    buffer = BytesIO()
    styles = getSampleStyleSheet()

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
    contact = "<br/>".join(escape(x) for x in [BUSINESS_ADDRESS, BUSINESS_PHONE] if x)
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
        customer_lines.append(f"<b>Bill to:</b> {escape(str(order['customer']))}")
    if order.get("phone"):
        customer_lines.append(escape(str(order["phone"])))
    if order.get("address"):
        customer_lines.append(escape(str(order["address"])))

    order_lines = []
    if order.get("order_source"):
        order_lines.append(f"<b>Source:</b> {escape(str(order['order_source']))}")
    if order.get("order_taker"):
        order_lines.append(f"<b>Taken by:</b> {escape(str(order['order_taker']))}")

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

    if order.get("notes"):
        story.extend([
            Spacer(1, 5),
            Paragraph(f"<b>Notes:</b> {escape(str(order['notes']))}", small),
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
    doc.build(story)
    return buffer.getvalue()



def build_invoice_print_html(order: dict) -> str:
    """Build a compact, print-friendly HTML invoice for direct browser printing."""
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
        customer_bits.append(f'<strong>{escape(str(order["customer"]))}</strong>')
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

    contact = "<br>".join(escape(x) for x in [BUSINESS_ADDRESS, BUSINESS_PHONE] if x)
    notes_html = ""
    if order.get("notes"):
        notes_html = f'<div class="notes"><strong>Notes:</strong> {escape(str(order["notes"]))}</div>'

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
  .invoice {{ width: 135mm; max-width: 100%; margin: 0 auto; }}
  .header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }}
  .business {{ font-size:18px; font-weight:700; }}
  .muted {{ color:#666; font-size:10px; }}
  .invoice-id {{ text-align:right; }}
  .invoice-id .label {{ font-size:15px; font-weight:700; letter-spacing:.04em; }}
  .divider {{ border-top:1px solid #bbb; margin:8px 0; }}
  .details {{ display:flex; justify-content:space-between; gap:14px; }}
  .details > div:last-child {{ text-align:right; }}
  table {{ width:100%; border-collapse:collapse; margin-top:8px; }}
  th {{ background:#f2f2f2; font-weight:700; border-bottom:1px solid #aaa; }}
  th, td {{ padding:5px 4px; text-align:left; vertical-align:top; }}
  td {{ border-bottom:1px solid #e2e2e2; }}
  .num {{ text-align:right; white-space:nowrap; }}
  .totals {{ width:48%; margin:8px 0 0 auto; }}
  .totals div {{ display:flex; justify-content:space-between; padding:2px 0; }}
  .totals .grand {{ border-top:1px solid #777; margin-top:3px; padding-top:5px; font-size:14px; font-weight:700; }}
  .notes {{ margin-top:8px; font-size:10px; }}
  .footer {{ margin-top:9px; text-align:center; color:#666; font-size:9px; }}
  @media print {{
    .invoice {{ width:100%; }}
  }}
</style>
</head>
<body>
  <div class="invoice">
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
    <table>
      <thead><tr><th>Item</th><th class="num">Qty</th><th class="num">Unit</th><th class="num">Amount</th></tr></thead>
      <tbody>{items_html}</tbody>
    </table>
    <div class="totals">
      <div><span>Subtotal</span><span>{escape(money(order['subtotal']))}</span></div>
      {adjustments}
      <div class="grand"><span>Total</span><span>{escape(money(order['total']))}</span></div>
    </div>
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


def fetch_order_for_pdf(order_id: int) -> dict:
    db = get_db()
    row = db.table("orders").select("*").eq("id", order_id).single().execute().data
    items = db.table("order_items").select("dish,qty,quantity_label,unit_price,line_total").eq("order_id", order_id).order("id").execute().data or []
    created = local_datetime(row["created_at"])
    return {
        "invoice_number": row["invoice_number"], "date": created.strftime("%B %d, %Y %I:%M %p"),
        "order_source": row.get("order_source"), "order_taker": row.get("order_taker"), "customer": row.get("customer"),
        "phone": row.get("phone"), "address": row.get("address"), "notes": row.get("notes"),
        "items": [{"dish": i["dish"], "qty": float(i["qty"]), "quantity_label": i.get("quantity_label") or str(i["qty"]),
                   "price": float(i["unit_price"]), "line_total": float(i["line_total"])} for i in items],
        "subtotal": float(row["subtotal"]), "delivery_fee": float(row["delivery_fee"]), "discount": float(row["discount"]),
        "tax_percent": float(row["tax_percent"]), "tax_amount": float(row["tax_amount"]), "total": float(row["total"]),
    }


def create_staff_order(order_taker, customer, phone, address, notes, cart, delivery_fee, discount, tax_percent):
    payload = [{"menu_item_id": int(i["menu_item_id"]), "qty": float(i["qty"]), "quantity_label": i.get("quantity_label") or str(i["qty"])} for i in cart]
    r = get_db().rpc("create_kitchen_order", {"p_order_taker": order_taker or None, "p_customer": customer or None,
        "p_phone": phone or None, "p_address": address or None, "p_notes": notes or None, "p_items": payload,
        "p_delivery_fee": float(delivery_fee), "p_discount": float(discount), "p_tax_percent": float(tax_percent)}).execute()
    if not r.data: raise RuntimeError("Supabase did not return the newly created order.")
    return r.data[0] if isinstance(r.data, list) else r.data


def create_public_order(customer, phone, address, notes, cart):
    payload = [{"menu_option_id": int(i["option_id"]), "qty": float(i["qty"]), "quantity_label": i.get("quantity_label") or str(i["qty"])} for i in cart]
    r = get_db().rpc("create_public_order", {"p_customer": customer, "p_phone": phone, "p_address": address or None,
        "p_notes": notes or None, "p_items": payload}).execute()
    if not r.data: raise RuntimeError("Supabase did not return the newly created order.")
    return r.data[0] if isinstance(r.data, list) else r.data


def update_order_payment(order_id, status, method, receiver):
    r = get_db().rpc("update_order_payment", {"p_order_id": int(order_id), "p_payment_status": status,
        "p_payment_method": method, "p_received_by": receiver}).execute()
    return r.data[0] if isinstance(r.data, list) and r.data else r.data


def update_order_workflow(order_id, status, assigned_to):
    r = get_db().rpc("update_order_workflow", {"p_order_id": int(order_id), "p_order_status": status,
        "p_assigned_to": assigned_to}).execute()
    return r.data[0] if isinstance(r.data, list) and r.data else r.data


def cart_item_is_tray(item: dict) -> bool:
    return str(item.get("category") or "").strip().casefold() in {"main", "side"}


def cart_quantity_label(item: dict, qty: float) -> str:
    if cart_item_is_tray(item):
        qtxt = f"{qty:g}"
        return f"{qtxt} tray" if abs(qty - 1.0) < 1e-9 else f"{qtxt} trays"
    return str(int(round(qty)))


def adjust_public_cart_item(index: int, delta: float) -> None:
    item = st.session_state.public_cart[index]
    is_tray = cart_item_is_tray(item)
    minimum = 0.5 if is_tray else 1.0
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
            st.caption("Open Order history to assign or confirm them. The badge clears as orders leave New status.")


if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    st.title(f"🍽️ {BUSINESS_NAME} Orders")
    st.error("Supabase credentials are not configured.")
    st.stop()

try:
    menu = load_menu()
    public_menu = load_public_menu()
    managers = load_managers()
except Exception as exc:
    st.title(f"🍽️ {BUSINESS_NAME}")
    st.error(f"Could not connect to the ordering database: {exc}")
    st.stop()

for key, default in [("public_cart", []), ("staff_cart", []), ("public_confirmation", None), ("staff_invoice", None), ("manager_authenticated", False), ("show_manager_notifications", False)]:
    if key not in st.session_state:
        st.session_state[key] = default

st.title(f"🍽️ {BUSINESS_NAME}")
st.caption("Browse the menu and place an order online, or sign in to the manager area.")
public_tab, manager_tab = st.tabs(["🍽️ Menu & Order", "🔐 Manager"])

with public_tab:
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
                            if str(menu_category).strip().casefold() in {"main", "side"}:
                                option_parts.append(f"{escape(price_text)} / tray")
                            else:
                                option_parts.append(escape(price_text))
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
        option_id = st.selectbox("Size / option", option_ids,
            format_func=lambda oid: f"{dish_df.loc[dish_df['option_id']==oid, 'option'].iloc[0]} — {money(dish_df.loc[dish_df['option_id']==oid, 'price'].iloc[0])}",
            key="public_option")
        qcol, acol = st.columns([1,2])
        selected = dish_df.loc[dish_df["option_id"] == option_id].iloc[0]
        with qcol:
            if str(category).strip().casefold() in {"main", "side"}:
                qty = float(st.number_input(
                    "Tray quantity",
                    min_value=0.5,
                    max_value=20.0,
                    value=1.0,
                    step=0.5,
                    format="%.1f",
                    key="public_tray_qty",
                    help="Enter the number of trays, for example 0.5, 1, 1.5, or 2.",
                ))
                qty_text = f"{qty:g}"
                quantity_label = f"{qty_text} tray" if abs(qty - 1.0) < 1e-9 else f"{qty_text} trays"
                st.caption(f"Enter trays as a number (for example 0.5 or 1.5). Price per tray: {money(float(selected['price']))}")
            else:
                qty = float(st.number_input("Quantity", min_value=1, max_value=100, value=1, step=1, key="public_qty"))
                quantity_label = str(int(qty))
        with acol:
            st.write("")
            st.write("")
            if st.button("Add to cart", type="primary", use_container_width=True):
                st.session_state.public_cart.append({"option_id": int(option_id), "dish": dish,
                    "category": str(category), "option": str(selected["option"]), "qty": float(qty),
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
                    is_tray = cart_item_is_tray(item)
                    step = 0.5 if is_tray else 1.0
                    minimum = 0.5 if is_tray else 1.0
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
                    is_tray = cart_item_is_tray(item)
                    step = 0.5 if is_tray else 1.0
                    minimum = 0.5 if is_tray else 1.0
                    qty_value = float(item.get("qty", minimum))
                    display_qty = str(item.get("quantity_label") or cart_quantity_label(item, qty_value))
                    unit_note = "per tray" if is_tray else "each"

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

with manager_tab:
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

        staff_tab, history_tab, menu_tab, announcement_tab = st.tabs(["Staff order", "Order history", "Menu", "Announcements"])

        with staff_tab:
            if menu.empty:
                st.warning("No available menu items.")
            else:
                c1,c2 = st.columns(2)
                with c1:
                    order_taker = st.selectbox("Order taken by", managers if managers else [""], key="staff_order_taker")
                    customer = st.text_input("Customer name", key="staff_customer")
                    phone = st.text_input("Phone", key="staff_phone")
                with c2:
                    address = st.text_area("Address", height=68, key="staff_address")
                    notes = st.text_area("Order notes", height=68, key="staff_notes")
                st.markdown("### Add dishes")
                categories = sorted(menu["category"].fillna("Menu").astype(str).str.strip().replace("", "Menu").unique().tolist(), key=str.casefold)
                cc,dc,qc = st.columns([2,3,1.5])
                with cc:
                    category = st.selectbox("Category", categories, key="staff_category")
                cat = menu[menu["category"].fillna("Menu").astype(str).str.strip().replace("", "Menu") == category].copy()
                with dc:
                    item_id = st.selectbox("Dish", cat["id"].astype(int).tolist(),
                        format_func=lambda iid: cat.loc[cat["id"]==iid, "dish"].iloc[0], key=f"staff_dish_{category}")
                with qc:
                    qty_text = st.text_input("Quantity", value="1", help="Examples: 2, 1/2 tray, 1 1/2 trays", key="staff_qty")
                selected = cat.loc[cat["id"]==item_id].iloc[0]
                st.caption(f"{money(float(selected['price']))} per base unit/tray")
                if st.button("Add to staff order", type="primary", use_container_width=True):
                    try:
                        qv,ql = parse_quantity(qty_text)
                        st.session_state.staff_cart.append({"menu_item_id": int(item_id), "dish": str(selected["dish"]),
                            "qty": qv, "quantity_label": ql, "price": float(selected["price"]), "line_total": qv*float(selected["price"])})
                        st.session_state.staff_invoice = None; st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
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
                            created = create_staff_order(order_taker, customer, phone, address, notes, st.session_state.staff_cart, delivery, discount, tax)
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
                        st.download_button("Download PDF invoice", data=inv["pdf"], file_name=f"{inv['number']}.pdf", mime="application/pdf", use_container_width=True)
                    with print_col:
                        if inv.get("order"):
                            render_print_button(inv["order"])


        with history_tab:
            h1,h2 = st.columns([3,1]); h1.subheader("Recent orders")
            if h2.button("Refresh", use_container_width=True): load_recent_orders.clear(); st.rerun()
            orders = load_recent_orders()
            if orders.empty:
                st.info("No orders yet.")
            else:
                display = orders.copy()
                display["created_at"] = display["created_at"].map(lambda x: local_datetime(x).strftime("%b %d, %Y %I:%M %p"))
                display["total"] = display["total"].map(money)
                display = display.rename(columns={"invoice_number":"Invoice","created_at":"Date","order_source":"Source","order_taker":"Taken by",
                    "assigned_to":"Assigned to","customer":"Customer","total":"Total","payment_status":"Payment","payment_method":"Method",
                    "payment_received_by":"Received by","order_status":"Status"})
                for col in ["Taken by","Assigned to","Method","Received by"]: display[col] = display[col].fillna("-")
                st.dataframe(display[["Invoice","Date","Source","Customer","Total","Status","Assigned to","Payment","Method","Received by","Taken by"]],
                             use_container_width=True, hide_index=True)
                chosen = st.selectbox("Select order", orders["invoice_number"].tolist(), key="history_order")
                row = orders.loc[orders["invoice_number"]==chosen].iloc[0]
                st.markdown("#### Order workflow")
                statuses = ["New","Confirmed","Preparing","Ready","Delivered","Cancelled"]
                current_status = str(row.get("order_status") or "New")
                assigned = str(row.get("assigned_to") or "")
                assign_opts = [""] + managers
                if assigned and assigned not in assign_opts: assign_opts.append(assigned)
                w1,w2,w3 = st.columns([1.5,1.5,1])
                status = w1.selectbox("Order status", statuses, index=statuses.index(current_status) if current_status in statuses else 0, key=f"status_{row['id']}")
                assignee = w2.selectbox("Assigned to", assign_opts, index=assign_opts.index(assigned) if assigned in assign_opts else 0, key=f"assign_{row['id']}")
                w3.write(""); w3.write("")
                if w3.button("Save status", type="primary", use_container_width=True, key=f"save_status_{row['id']}"):
                    try:
                        update_order_workflow(int(row["id"]), status, assignee or None); load_recent_orders.clear(); st.success("Order updated."); st.rerun()
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
                    dl_col, print_col = st.columns(2)
                    with dl_col:
                        st.download_button("Download selected invoice", data=pdf, file_name=f"{chosen}.pdf", mime="application/pdf", use_container_width=True)
                    with print_col:
                        render_print_button(old)
                except Exception as exc: st.warning(f"Could not prepare invoice: {exc}")

        with menu_tab:
            st.subheader("Public menu")
            if public_menu.empty:
                st.info("No public menu options.")
            else:
                md = public_menu[["category","dish","option","price"]].copy(); md["price"] = md["price"].map(money)
                md.columns = ["Category","Dish","Option","Price"]
                st.dataframe(md, use_container_width=True, hide_index=True)
            st.caption("Edit dishes in Supabase → menu and customer-facing sizes/prices in Supabase → menu_options. Existing dishes have a Standard option automatically.")

        with announcement_tab:
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


st.divider()
st.caption(f"© {BUSINESS_NAME} · Online orders are submitted directly to the kitchen database.")
