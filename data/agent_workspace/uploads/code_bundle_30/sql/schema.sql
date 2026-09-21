create table users (
  id integer primary key,
  email text not null unique,
  created_at text not null
);
