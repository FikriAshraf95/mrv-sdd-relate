-- SPEC-02 courts and opening_hours (opening hours are per court, D001)
create table courts (
    id uuid primary key,
    name text not null unique,
    surface text not null,
    indoor boolean not null
);

create table opening_hours (
    id uuid primary key,
    court_id uuid not null references courts (id) on delete cascade,
    weekday int not null,
    opens_at time not null,
    closes_at time not null
);
create index opening_hours_court_id on opening_hours (court_id);
