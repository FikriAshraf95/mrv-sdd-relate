-- SPEC-02 bookings (end time instead of a duration, D002; kept when cancelled, D003)
create table bookings (
    id uuid primary key,
    member_id uuid not null references members (id) on delete restrict,
    court_id uuid not null references courts (id) on delete restrict,
    starts_at timestamptz not null,
    ends_at timestamptz not null,
    status text not null check (status in ('held', 'confirmed', 'cancelled')),
    cancelled_at timestamptz,
    created_at timestamptz not null
);
create index bookings_member_id on bookings (member_id);
create index bookings_court_id_starts_at on bookings (court_id, starts_at);
