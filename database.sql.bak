-- Home Kitchen Invoice App - Supabase schema
-- Run this entire file once in Supabase: SQL Editor -> New query -> Run.

create sequence if not exists public.invoice_number_seq start 1;

create table if not exists public.menu (
    id bigint generated always as identity primary key,
    dish text not null unique,
    category text not null default 'Menu',
    price numeric(10,2) not null check (price >= 0),
    available boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.orders (
    id bigint generated always as identity primary key,
    invoice_number text not null unique
        default ('HK-' || lpad(nextval('public.invoice_number_seq')::text, 6, '0')),
    created_at timestamptz not null default now(),
    order_taker text,
    customer text,
    phone text,
    address text,
    notes text,
    subtotal numeric(12,2) not null default 0 check (subtotal >= 0),
    delivery_fee numeric(12,2) not null default 0 check (delivery_fee >= 0),
    discount numeric(12,2) not null default 0 check (discount >= 0),
    tax_percent numeric(7,3) not null default 0 check (tax_percent >= 0),
    tax_amount numeric(12,2) not null default 0 check (tax_amount >= 0),
    total numeric(12,2) not null default 0 check (total >= 0),
    payment_status text not null default 'Unpaid',
    order_status text not null default 'New'
);

create table if not exists public.order_items (
    id bigint generated always as identity primary key,
    order_id bigint not null references public.orders(id) on delete cascade,
    menu_item_id bigint references public.menu(id) on delete set null,
    dish text not null,
    qty integer not null check (qty > 0),
    unit_price numeric(10,2) not null check (unit_price >= 0),
    line_total numeric(12,2) not null check (line_total >= 0)
);

create index if not exists orders_created_at_idx on public.orders(created_at desc);
create index if not exists order_items_order_id_idx on public.order_items(order_id);

create or replace function public.touch_menu_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists menu_touch_updated_at on public.menu;
create trigger menu_touch_updated_at
before update on public.menu
for each row execute function public.touch_menu_updated_at();

-- One transactional RPC call creates an order, snapshots current menu prices,
-- calculates totals on the database side, and creates all line items.
create or replace function public.create_kitchen_order(
    p_order_taker text,
    p_customer text,
    p_phone text,
    p_address text,
    p_notes text,
    p_items jsonb,
    p_delivery_fee numeric default 0,
    p_discount numeric default 0,
    p_tax_percent numeric default 0
)
returns table (
    order_id bigint,
    invoice_number text,
    created_at timestamptz,
    subtotal numeric,
    tax_amount numeric,
    total numeric
)
language plpgsql
security definer
set search_path = public
as $$
declare
    v_order_id bigint;
    v_invoice_number text;
    v_created_at timestamptz;
    v_item jsonb;
    v_menu_id bigint;
    v_qty integer;
    v_dish text;
    v_price numeric(10,2);
    v_subtotal numeric(12,2) := 0;
    v_delivery numeric(12,2) := greatest(coalesce(p_delivery_fee, 0), 0);
    v_discount numeric(12,2) := greatest(coalesce(p_discount, 0), 0);
    v_tax_percent numeric(7,3) := greatest(coalesce(p_tax_percent, 0), 0);
    v_taxable numeric(12,2);
    v_tax_amount numeric(12,2);
    v_total numeric(12,2);
begin
    if p_items is null or jsonb_typeof(p_items) <> 'array' or jsonb_array_length(p_items) = 0 then
        raise exception 'Order must contain at least one item';
    end if;

    insert into public.orders (
        order_taker, customer, phone, address, notes,
        subtotal, delivery_fee, discount, tax_percent, tax_amount, total
    ) values (
        nullif(trim(p_order_taker), ''),
        nullif(trim(p_customer), ''),
        nullif(trim(p_phone), ''),
        nullif(trim(p_address), ''),
        nullif(trim(p_notes), ''),
        0, v_delivery, v_discount, v_tax_percent, 0, 0
    )
    returning id, orders.invoice_number, orders.created_at
    into v_order_id, v_invoice_number, v_created_at;

    for v_item in select value from jsonb_array_elements(p_items)
    loop
        v_menu_id := nullif(v_item->>'menu_item_id', '')::bigint;
        v_qty := coalesce(nullif(v_item->>'qty', '')::integer, 0);

        if v_menu_id is null or v_qty <= 0 then
            raise exception 'Invalid menu item or quantity';
        end if;

        select m.dish, m.price
        into v_dish, v_price
        from public.menu m
        where m.id = v_menu_id and m.available = true;

        if not found then
            raise exception 'Menu item % is unavailable or does not exist', v_menu_id;
        end if;

        insert into public.order_items (
            order_id, menu_item_id, dish, qty, unit_price, line_total
        ) values (
            v_order_id, v_menu_id, v_dish, v_qty, v_price, round(v_price * v_qty, 2)
        );

        v_subtotal := v_subtotal + round(v_price * v_qty, 2);
    end loop;

    v_discount := least(v_discount, v_subtotal + v_delivery);
    v_taxable := greatest(v_subtotal + v_delivery - v_discount, 0);
    v_tax_amount := round(v_taxable * v_tax_percent / 100.0, 2);
    v_total := round(v_taxable + v_tax_amount, 2);

    update public.orders
    set subtotal = v_subtotal,
        delivery_fee = v_delivery,
        discount = v_discount,
        tax_percent = v_tax_percent,
        tax_amount = v_tax_amount,
        total = v_total
    where id = v_order_id;

    return query
    select v_order_id, v_invoice_number, v_created_at,
           v_subtotal, v_tax_amount, v_total;
end;
$$;

-- Keep these tables inaccessible to browser clients by default.
alter table public.menu enable row level security;
alter table public.orders enable row level security;
alter table public.order_items enable row level security;

revoke all on function public.create_kitchen_order(text,text,text,text,text,jsonb,numeric,numeric,numeric)
from public, anon, authenticated;
grant execute on function public.create_kitchen_order(text,text,text,text,text,jsonb,numeric,numeric,numeric)
to service_role;

-- Starter menu. Edit or delete these rows in Supabase Table Editor.
insert into public.menu (dish, category, price, available) values
    ('Pasta', 'Main', 12.00, true),
    ('Chicken Biryani', 'Main', 15.00, true),
    ('Beef Curry', 'Main', 16.00, true),
    ('Salad', 'Side', 6.00, true)
on conflict (dish) do nothing;
