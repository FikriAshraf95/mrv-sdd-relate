-- SPEC-02 payments and refunds
create table payments (
    id uuid primary key,
    booking_id uuid not null references bookings (id) on delete restrict,
    amount_cents int not null,
    captured_at timestamptz
);
create index payments_booking_id on payments (booking_id);

create table refunds (
    id uuid primary key,
    payment_id uuid not null references payments (id) on delete restrict,
    amount_cents int not null,
    reason text not null
);
create index refunds_payment_id on refunds (payment_id);
