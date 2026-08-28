from __future__ import annotations

from datetime import datetime
from fractions import Fraction
import re
from html import escape
from io import BytesIO
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from supabase import Client, create_client


st.set_page_config(page_title="Shukriya's Kitchen", page_icon="🍽️", layout="centered")


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
    """Return the first non-empty top-level Streamlit secret or environment variable."""
    import os

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


BUSINESS_NAME = setting("BUSINESS_NAME", "My Home Kitchen")
BUSINESS_PHONE = setting("BUSINESS_PHONE", "")
BUSINESS_ADDRESS = setting("BUSINESS_ADDRESS", "")
CURRENCY = setting("CURRENCY", "$")
APP_TIMEZONE = setting("APP_TIMEZONE", "America/Los_Angeles")
APP_PASSWORD = setting("APP_PASSWORD", "")

# Prefer simple top-level Streamlit secrets. Keep nested names for backward compatibility.
SUPABASE_URL = (
    first_secret("SUPABASE_URL", "supabase_url")
    or nested_secret("supabase", "url")
).strip()
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
        get_db()
        .table("menu")
        .select("id,dish,category,price,available")
        .eq("available", True)
        .order("category")
        .order("dish")
        .execute()
    )
    df = pd.DataFrame(response.data or [])
    if df.empty:
        return pd.DataFrame(columns=["id", "dish", "category", "price", "available"])
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    return df.dropna(subset=["price"]).reset_index(drop=True)


@st.cache_data(ttl=10, show_spinner=False)
def load_recent_orders(limit: int = 50) -> pd.DataFrame:
    response = (
        get_db()
        .table("orders")
        .select(
            "id,invoice_number,created_at,order_taker,customer,phone,total,payment_status,order_status"
        )
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return pd.DataFrame(response.data or [])



def parse_quantity(text: str) -> tuple[float, str]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Enter a quantity, for example 2, 1/2 tray, or 1 1/2 trays.")

    normalized = raw.lower().replace("trays", "tray").strip()
    unit = "tray" if "tray" in normalized else ""
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

    label = raw
    return round(value, 3), label

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
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        rightMargin=0.6 * inch,
        leftMargin=0.6 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
        title=f"Invoice {order['invoice_number']}",
        author=BUSINESS_NAME,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvoiceTitle",
        parent=styles["Title"],
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    right_style = ParagraphStyle(
        "Right",
        parent=styles["BodyText"],
        alignment=TA_RIGHT,
        fontSize=9,
        leading=12,
    )
    small = ParagraphStyle("Small", parent=styles["BodyText"], fontSize=9, leading=12)

    story = [Paragraph(escape(BUSINESS_NAME), title_style)]
    contact = " | ".join(x for x in [BUSINESS_ADDRESS, BUSINESS_PHONE] if x)
    if contact:
        story.append(
            Paragraph(escape(contact), ParagraphStyle("Contact", parent=small, alignment=TA_CENTER))
        )
    story.extend([Spacer(1, 0.18 * inch), Paragraph("INVOICE", styles["Heading2"])])

    meta_left = [
        f"<b>Invoice:</b> {escape(str(order['invoice_number']))}",
        f"<b>Date:</b> {escape(str(order['date']))}",
        f"<b>Taken by:</b> {escape(str(order.get('order_taker') or '-'))}",
    ]
    meta_right = [
        f"<b>Customer:</b> {escape(str(order.get('customer') or '-'))}",
        f"<b>Phone:</b> {escape(str(order.get('phone') or '-'))}",
        f"<b>Address:</b> {escape(str(order.get('address') or '-'))}",
    ]
    meta = Table(
        [[Paragraph("<br/>".join(meta_left), small), Paragraph("<br/>".join(meta_right), right_style)]],
        colWidths=[3.6 * inch, 3.2 * inch],
    )
    meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.extend([meta, Spacer(1, 0.2 * inch)])

    rows = [["Item", "Qty", "Unit Price", "Amount"]]
    for item in order["items"]:
        rows.append(
            [
                escape(str(item["dish"])),
                str(item.get("quantity_label") or item["qty"]),
                money(item["price"]),
                money(item["line_total"]),
            ]
        )

    table = Table(rows, colWidths=[3.55 * inch, 0.6 * inch, 1.25 * inch, 1.4 * inch], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("ALIGN", (1, 0), (-1, 0), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BBBBBB")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([table, Spacer(1, 0.18 * inch)])

    totals = [
        ["Subtotal", money(order["subtotal"])],
        ["Delivery", money(order["delivery_fee"])],
        ["Discount", f"-{money(order['discount'])}"],
        [f"Tax ({float(order['tax_percent']):.2f}%)", money(order["tax_amount"])],
        ["TOTAL", money(order["total"])],
    ]
    total_table = Table(totals, colWidths=[5.4 * inch, 1.4 * inch], hAlign="RIGHT")
    total_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(total_table)

    if order.get("notes"):
        story.extend(
            [
                Spacer(1, 0.2 * inch),
                Paragraph("<b>Notes</b>", small),
                Paragraph(escape(str(order["notes"])), small),
            ]
        )

    story.extend(
        [
            Spacer(1, 0.28 * inch),
            Paragraph(
                "Thank you for your order!",
                ParagraphStyle("Thanks", parent=small, alignment=TA_CENTER),
            ),
        ]
    )
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def fetch_order_for_pdf(order_id: int) -> dict:
    db = get_db()
    order_resp = db.table("orders").select("*").eq("id", order_id).single().execute()
    item_resp = (
        db.table("order_items")
        .select("dish,qty,quantity_label,unit_price,line_total")
        .eq("order_id", order_id)
        .order("id")
        .execute()
    )
    row = order_resp.data
    created = local_datetime(row["created_at"])
    return {
        "invoice_number": row["invoice_number"],
        "date": created.strftime("%B %d, %Y %I:%M %p"),
        "order_taker": row.get("order_taker"),
        "customer": row.get("customer"),
        "phone": row.get("phone"),
        "address": row.get("address"),
        "notes": row.get("notes"),
        "items": [
            {
                "dish": item["dish"],
                "qty": float(item["qty"]),
                "quantity_label": item.get("quantity_label") or str(item["qty"]),
                "price": float(item["unit_price"]),
                "line_total": float(item["line_total"]),
            }
            for item in (item_resp.data or [])
        ],
        "subtotal": float(row["subtotal"]),
        "delivery_fee": float(row["delivery_fee"]),
        "discount": float(row["discount"]),
        "tax_percent": float(row["tax_percent"]),
        "tax_amount": float(row["tax_amount"]),
        "total": float(row["total"]),
    }


def create_order(
    *,
    order_taker: str,
    customer: str,
    phone: str,
    address: str,
    notes: str,
    cart: list[dict],
    delivery_fee: float,
    discount: float,
    tax_percent: float,
) -> dict:
    payload_items = [
        {"menu_item_id": int(item["menu_item_id"]), "qty": float(item["qty"]), "quantity_label": item.get("quantity_label") or str(item["qty"])} for item in cart
    ]
    response = get_db().rpc(
        "create_kitchen_order",
        {
            "p_order_taker": order_taker or None,
            "p_customer": customer or None,
            "p_phone": phone or None,
            "p_address": address or None,
            "p_notes": notes or None,
            "p_items": payload_items,
            "p_delivery_fee": float(delivery_fee),
            "p_discount": float(discount),
            "p_tax_percent": float(tax_percent),
        },
    ).execute()
    if not response.data:
        raise RuntimeError("Supabase did not return the newly created order.")
    return response.data[0] if isinstance(response.data, list) else response.data


def require_password() -> None:
    if not APP_PASSWORD:
        return
    if st.session_state.get("app_authenticated"):
        return

    st.title("🍽️ Shukriya's Kitchen")
    st.caption("Enter the shared app password to continue.")
    entered = st.text_input("App password", type="password")
    if st.button("Sign in", type="primary"):
        if entered == APP_PASSWORD:
            st.session_state.app_authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()


if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
    st.title("🍽️ Shukriya's Kitchen")
    st.error("Supabase credentials are not being detected by this Streamlit app.")
    st.write(
        {
            "Supabase URL detected": bool(SUPABASE_URL),
            "Supabase secret key detected": bool(SUPABASE_SECRET_KEY),
        }
    )
    st.markdown(
        """In **Streamlit Community Cloud → Manage app → Settings → Secrets**, use this exact top-level format:

```toml
SUPABASE_URL = "https://YOUR_PROJECT.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_YOUR_KEY"

BUSINESS_NAME = "My Home Kitchen"
CURRENCY = "$"
APP_TIMEZONE = "America/Los_Angeles"
APP_PASSWORD = "choose-a-password"
```

Save the secrets, then reboot the app. Do not put these credentials in GitHub."""
    )
    st.stop()

require_password()

if "cart" not in st.session_state:
    st.session_state.cart = []
if "generated_invoice" not in st.session_state:
    st.session_state.generated_invoice = None

st.title("🍽️ Shukriya's Kitchen")
st.caption("Shared menu, central order history, and PDF invoices powered by Supabase.")

try:
    menu = load_menu()
except Exception as exc:
    st.error(f"Could not connect to Supabase or load the menu: {exc}")
    st.stop()

new_order_tab, history_tab, menu_tab = st.tabs(["New order", "Order history", "Menu"])

with new_order_tab:
    if menu.empty:
        st.warning("No available menu items were found. Add items to the `menu` table in Supabase.")
    else:
        with st.expander("Customer & order details", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                order_taker = st.text_input("Order taken by", key="order_taker")
                customer = st.text_input("Customer name", key="customer")
                phone = st.text_input("Phone", key="phone")
            with c2:
                address = st.text_area("Address", height=68, key="address")
                notes = st.text_area("Order notes", height=68, key="notes")

        st.subheader("Add dishes")

        categories = sorted(
            menu["category"].fillna("Menu").astype(str).str.strip().replace("", "Menu").unique().tolist(),
            key=str.casefold,
        )
        category_col, dish_col, qty_col = st.columns([2, 3, 1.4])

        with category_col:
            selected_category = st.selectbox(
                "Category",
                options=categories,
                key="selected_category",
            )

        category_menu = menu[
            menu["category"].fillna("Menu").astype(str).str.strip().replace("", "Menu")
            == selected_category
        ].copy()

        with dish_col:
            selected_id = st.selectbox(
                "Dish",
                options=category_menu["id"].astype(int).tolist(),
                format_func=lambda item_id: category_menu.loc[
                    category_menu["id"] == item_id, "dish"
                ].iloc[0],
                key=f"dish_for_{selected_category}",
            )

        with qty_col:
            qty_text = st.text_input(
                "Quantity",
                value="1",
                help="Examples: 2, 1/2, 1 tray, 1/2 tray, 1 1/2 trays",
                key="quantity_input",
            )

        selected = category_menu.loc[category_menu["id"] == selected_id].iloc[0]
        st.caption(f"{money(float(selected['price']))} per base unit/tray")

        if st.button("Add to order", type="primary", use_container_width=True):
            try:
                qty_value, qty_label = parse_quantity(qty_text)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state.cart.append(
                    {
                        "menu_item_id": int(selected_id),
                        "dish": str(selected["dish"]),
                        "qty": qty_value,
                        "quantity_label": qty_label,
                        "price": float(selected["price"]),
                        "line_total": qty_value * float(selected["price"]),
                    }
                )
                st.session_state.generated_invoice = None
                st.rerun()

        st.subheader("Current order")
        if not st.session_state.cart:
            st.info("No items added yet.")
        else:
            for idx, item in enumerate(st.session_state.cart):
                cols = st.columns([4, 1, 2, 1])
                cols[0].write(f"**{item['dish']}**")
                cols[1].write(f"× {item.get('quantity_label') or item['qty']}")
                cols[2].write(money(item["line_total"]))
                if cols[3].button("✕", key=f"remove_{idx}"):
                    st.session_state.cart.pop(idx)
                    st.session_state.generated_invoice = None
                    st.rerun()

            displayed_subtotal = sum(i["line_total"] for i in st.session_state.cart)
            a, b, c = st.columns(3)
            with a:
                delivery_fee = st.number_input(
                    "Delivery fee", min_value=0.0, value=0.0, step=1.0, key="delivery_fee"
                )
            with b:
                discount = st.number_input(
                    "Discount", min_value=0.0, value=0.0, step=1.0, key="discount"
                )
            with c:
                tax_percent = st.number_input(
                    "Tax %", min_value=0.0, value=0.0, step=0.25, key="tax_percent"
                )

            displayed_taxable = max(0.0, displayed_subtotal + delivery_fee - discount)
            displayed_tax = displayed_taxable * tax_percent / 100
            displayed_total = displayed_taxable + displayed_tax

            st.markdown(
                f"**Subtotal:** {money(displayed_subtotal)}  \n"
                f"**Delivery:** {money(delivery_fee)}  \n"
                f"**Discount:** -{money(discount)}  \n"
                f"**Tax:** {money(displayed_tax)}  \n"
                f"### Estimated total: {money(displayed_total)}"
            )
            st.caption("Final prices are re-checked against Supabase when the order is submitted.")

            g1, g2 = st.columns(2)
            with g1:
                if st.button("Clear order", use_container_width=True):
                    st.session_state.cart = []
                    st.session_state.generated_invoice = None
                    st.rerun()
            with g2:
                if st.button("Save & generate invoice", type="primary", use_container_width=True):
                    try:
                        created = create_order(
                            order_taker=order_taker,
                            customer=customer,
                            phone=phone,
                            address=address,
                            notes=notes,
                            cart=st.session_state.cart,
                            delivery_fee=float(delivery_fee),
                            discount=float(discount),
                            tax_percent=float(tax_percent),
                        )
                        order = fetch_order_for_pdf(int(created["order_id"]))
                        st.session_state.generated_invoice = {
                            "number": order["invoice_number"],
                            "pdf": build_invoice_pdf(order),
                        }
                        st.session_state.cart = []
                        load_recent_orders.clear()
                    except Exception as exc:
                        st.error(f"Could not save the order: {exc}")

            if st.session_state.generated_invoice:
                inv = st.session_state.generated_invoice
                st.success(f"Invoice {inv['number']} saved and created.")
                st.download_button(
                    "Download PDF invoice",
                    data=inv["pdf"],
                    file_name=f"{inv['number']}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )

with history_tab:
    h1, h2 = st.columns([3, 1])
    with h1:
        st.subheader("Recent orders")
    with h2:
        if st.button("Refresh", key="refresh_orders", use_container_width=True):
            load_recent_orders.clear()
            st.rerun()

    try:
        orders = load_recent_orders()
    except Exception as exc:
        st.error(f"Could not load order history: {exc}")
        orders = pd.DataFrame()

    if orders.empty:
        st.info("No saved orders yet.")
    else:
        display = orders.copy()
        display["created_at"] = display["created_at"].map(
            lambda x: local_datetime(x).strftime("%b %d, %Y %I:%M %p")
        )
        display["total"] = display["total"].map(money)
        display = display.rename(
            columns={
                "invoice_number": "Invoice",
                "created_at": "Date",
                "order_taker": "Taken by",
                "customer": "Customer",
                "phone": "Phone",
                "total": "Total",
                "payment_status": "Payment",
                "order_status": "Status",
            }
        )
        st.dataframe(
            display[["Invoice", "Date", "Customer", "Total", "Payment", "Status", "Taken by"]],
            use_container_width=True,
            hide_index=True,
        )

        invoice_options = orders["invoice_number"].tolist()
        chosen_invoice = st.selectbox("Reprint invoice", invoice_options)
        chosen_row = orders.loc[orders["invoice_number"] == chosen_invoice].iloc[0]
        try:
            old_order = fetch_order_for_pdf(int(chosen_row["id"]))
            old_pdf = build_invoice_pdf(old_order)
            st.download_button(
                "Download selected invoice",
                data=old_pdf,
                file_name=f"{chosen_invoice}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as exc:
            st.warning(f"Could not prepare that invoice: {exc}")

with menu_tab:
    m1, m2 = st.columns([3, 1])
    with m1:
        st.subheader("Current menu")
    with m2:
        if st.button("Refresh menu", use_container_width=True):
            load_menu.clear()
            st.rerun()

    if menu.empty:
        st.info("No available menu items.")
    else:
        menu_display = menu[["dish", "category", "price"]].copy()
        menu_display["price"] = menu_display["price"].map(money)
        menu_display.columns = ["Dish", "Category", "Price"]
        st.dataframe(menu_display, use_container_width=True, hide_index=True)
    st.caption(
        "For this version, add dishes or change prices/availability in Supabase → Table Editor → menu. "
        "Changes appear here within about 30 seconds, or immediately after Refresh menu."
    )

st.divider()
st.caption("Supabase stores menu data, orders, and invoice line items centrally for all users.")
