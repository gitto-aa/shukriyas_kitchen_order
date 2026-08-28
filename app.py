from __future__ import annotations

from datetime import datetime
from fractions import Fraction
from html import escape
from io import BytesIO
from zoneinfo import ZoneInfo
import os

import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from supabase import Client, create_client

st.set_page_config(page_title="Shukriya's Kitchen Orders", page_icon="🍽️", layout="centered")


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


@st.cache_data(ttl=10, show_spinner=False)
def load_recent_orders(limit: int = 100) -> pd.DataFrame:
    response = (
        get_db().table("orders")
        .select("id,invoice_number,created_at,order_source,order_taker,assigned_to,customer,phone,total,payment_status,payment_method,payment_received_by,paid_at,order_status")
        .order("created_at", desc=True).limit(limit).execute()
    )
    return pd.DataFrame(response.data or [])


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
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER, rightMargin=.6*inch, leftMargin=.6*inch,
                            topMargin=.55*inch, bottomMargin=.55*inch,
                            title=f"Invoice {order['invoice_number']}", author=BUSINESS_NAME)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("InvoiceTitle", parent=styles["Title"], fontSize=18, leading=22,
                                 alignment=TA_CENTER, spaceAfter=6)
    right_style = ParagraphStyle("Right", parent=styles["BodyText"], alignment=TA_RIGHT, fontSize=9, leading=12)
    small = ParagraphStyle("Small", parent=styles["BodyText"], fontSize=9, leading=12)
    story = [Paragraph(escape(BUSINESS_NAME), title_style)]
    contact = " | ".join(x for x in [BUSINESS_ADDRESS, BUSINESS_PHONE] if x)
    if contact:
        story.append(Paragraph(escape(contact), ParagraphStyle("Contact", parent=small, alignment=TA_CENTER)))
    story += [Spacer(1, .18*inch), Paragraph("INVOICE", styles["Heading2"])]
    left = [f"<b>Invoice:</b> {escape(str(order['invoice_number']))}",
            f"<b>Date:</b> {escape(str(order['date']))}",
            f"<b>Source:</b> {escape(str(order.get('order_source') or 'Staff'))}",
            f"<b>Taken by:</b> {escape(str(order.get('order_taker') or '-'))}"]
    right = [f"<b>Customer:</b> {escape(str(order.get('customer') or '-'))}",
             f"<b>Phone:</b> {escape(str(order.get('phone') or '-'))}",
             f"<b>Address:</b> {escape(str(order.get('address') or '-'))}"]
    meta = Table([[Paragraph("<br/>".join(left), small), Paragraph("<br/>".join(right), right_style)]],
                 colWidths=[3.6*inch, 3.2*inch])
    meta.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
    story += [meta, Spacer(1, .2*inch)]
    rows = [["Item", "Qty", "Unit Price", "Amount"]]
    for item in order["items"]:
        rows.append([escape(str(item["dish"])), str(item.get("quantity_label") or item["qty"]),
                     money(item["price"]), money(item["line_total"])])
    table = Table(rows, colWidths=[3.55*inch,.9*inch,1.05*inch,1.3*inch], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#EEEEEE")), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("ALIGN", (1,0), (-1,-1), "RIGHT"), ("GRID", (0,0), (-1,-1), .5, colors.HexColor("#BBBBBB")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6)
    ]))
    story += [table, Spacer(1,.18*inch)]
    totals = [["Subtotal", money(order["subtotal"])], ["Delivery", money(order["delivery_fee"])],
              ["Discount", f"-{money(order['discount'])}"],
              [f"Tax ({float(order['tax_percent']):.2f}%)", money(order["tax_amount"])], ["TOTAL", money(order["total"])]]
    tt = Table(totals, colWidths=[5.4*inch,1.4*inch], hAlign="RIGHT")
    tt.setStyle(TableStyle([("ALIGN", (0,0), (-1,-1), "RIGHT"), ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
                            ("LINEABOVE", (0,-1), (-1,-1), 1, colors.black), ("TOPPADDING", (0,0), (-1,-1), 4),
                            ("BOTTOMPADDING", (0,0), (-1,-1), 4)]))
    story.append(tt)
    if order.get("notes"):
        story += [Spacer(1,.2*inch), Paragraph("<b>Notes</b>", small), Paragraph(escape(str(order["notes"])), small)]
    story += [Spacer(1,.28*inch), Paragraph("Thank you for your order!", ParagraphStyle("Thanks", parent=small, alignment=TA_CENTER))]
    doc.build(story)
    return buffer.getvalue()


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

for key, default in [("public_cart", []), ("staff_cart", []), ("public_confirmation", None), ("staff_invoice", None), ("manager_authenticated", False)]:
    if key not in st.session_state:
        st.session_state[key] = default

st.title(f"🍽️ {BUSINESS_NAME}")
st.caption("Browse the menu and place an order online, or sign in to the manager area.")
public_tab, manager_tab = st.tabs(["🍽️ Menu & Order", "🔐 Manager"])

with public_tab:
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
                            if str(menu_category).strip().casefold() == "main":
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
            if str(category).strip().casefold() == "main":
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
                    "option": str(selected["option"]), "qty": float(qty), "quantity_label": quantity_label,
                    "price": float(selected["price"]), "line_total": float(qty)*float(selected["price"])})
                st.session_state.public_confirmation = None
                st.rerun()

        st.markdown("### Your cart")
        if not st.session_state.public_cart:
            st.info("Your cart is empty.")
        else:
            for i, item in enumerate(st.session_state.public_cart):
                c1,c2,c3,c4 = st.columns([3.5,1.2,1.4,.7])
                c1.write(f"**{item['dish']}**  \n{item['option']}")
                c2.write(f"× {item.get('quantity_label') or item['qty']}")
                c3.write(money(item["line_total"]))
                if c4.button("✕", key=f"public_remove_{i}"):
                    st.session_state.public_cart.pop(i); st.rerun()
            subtotal = sum(i["line_total"] for i in st.session_state.public_cart)
            st.markdown(f"### Total: {money(subtotal)}")
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
        top1, top2 = st.columns([4,1])
        top1.subheader("Manager dashboard")
        if top2.button("Sign out", use_container_width=True):
            st.session_state.manager_authenticated = False; st.rerun()

        staff_tab, history_tab, menu_tab = st.tabs(["Staff order", "Order history", "Menu"])

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
                            st.session_state.staff_invoice = {"number": order["invoice_number"], "pdf": build_invoice_pdf(order)}
                            st.session_state.staff_cart = []; load_recent_orders.clear(); st.rerun()
                        except Exception as exc:
                            st.error(f"Could not save order: {exc}")
                if st.session_state.staff_invoice:
                    inv = st.session_state.staff_invoice
                    st.success(f"Invoice {inv['number']} saved.")
                    st.download_button("Download PDF invoice", data=inv["pdf"], file_name=f"{inv['number']}.pdf", mime="application/pdf", use_container_width=True)

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
                    st.download_button("Download selected invoice", data=pdf, file_name=f"{chosen}.pdf", mime="application/pdf", use_container_width=True)
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

st.divider()
st.caption(f"© {BUSINESS_NAME} · Online orders are submitted directly to the kitchen database.")
