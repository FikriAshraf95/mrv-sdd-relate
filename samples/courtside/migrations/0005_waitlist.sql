-- SPEC-02 waitlist_entries
create table waitlist_entries (
    id uuid primary key,
    court_id uuid not null references courts (id),
    member_id uuid not null references members (id),
    wanted_start timestamptz not null,
    promoted_booking_id uuid references bookings (id)
);
create index waitlist_entries_slot on waitlist_entries (court_id, wanted_start);
