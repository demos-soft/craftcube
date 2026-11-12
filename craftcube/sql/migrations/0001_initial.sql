-- CraftCube schema migration 0001: initial schema.
-- Mirrors roundcubemail/SQL/sqlite.initial.sql (Roundcube, GPL-3.0+),
-- reduced to the tables the app actually uses. This file is the baseline
-- version (schema_version 1); never edit it after it has shipped -
-- add the next numbered migration instead (see docs/DATABASE.md).

CREATE TABLE IF NOT EXISTS users (
  user_id integer NOT NULL PRIMARY KEY,
  username varchar(128) NOT NULL default '',
  mail_host varchar(128) NOT NULL default '',
  created datetime NOT NULL default '0000-00-00 00:00:00',
  last_login datetime DEFAULT NULL,
  failed_login datetime DEFAULT NULL,
  failed_login_counter integer DEFAULT NULL,
  language varchar(16),
  preferences text DEFAULT NULL,
  password text DEFAULT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users(username, mail_host);

CREATE TABLE IF NOT EXISTS contacts (
  contact_id integer NOT NULL PRIMARY KEY,
  user_id integer NOT NULL
    REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  changed datetime NOT NULL default '0000-00-00 00:00:00',
  del tinyint NOT NULL default '0',
  name varchar(128) NOT NULL default '',
  email text NOT NULL default '',
  firstname varchar(128) NOT NULL default '',
  surname varchar(128) NOT NULL default '',
  vcard text NOT NULL default '',
  words text NOT NULL default ''
);
CREATE INDEX IF NOT EXISTS ix_contacts_user_id ON contacts(user_id, del);

CREATE TABLE IF NOT EXISTS contactgroups (
  contactgroup_id integer NOT NULL PRIMARY KEY,
  user_id integer NOT NULL
    REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  changed datetime NOT NULL default '0000-00-00 00:00:00',
  del tinyint NOT NULL default '0',
  name varchar(128) NOT NULL default ''
);
CREATE INDEX IF NOT EXISTS ix_contactgroups_user_id ON contactgroups(user_id, del);

CREATE TABLE IF NOT EXISTS contactgroupmembers (
  contactgroup_id integer NOT NULL
    REFERENCES contactgroups(contactgroup_id) ON DELETE CASCADE ON UPDATE CASCADE,
  contact_id integer NOT NULL
    REFERENCES contacts(contact_id) ON DELETE CASCADE ON UPDATE CASCADE,
  created datetime NOT NULL default '0000-00-00 00:00:00',
  PRIMARY KEY (contactgroup_id, contact_id)
);
CREATE INDEX IF NOT EXISTS ix_contactgroupmembers_contact_id ON contactgroupmembers (contact_id);

CREATE TABLE IF NOT EXISTS identities (
  identity_id integer NOT NULL PRIMARY KEY,
  user_id integer NOT NULL
    REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  changed datetime NOT NULL default '0000-00-00 00:00:00',
  del tinyint NOT NULL default '0',
  standard tinyint NOT NULL default '0',
  name varchar(128) NOT NULL default '',
  organization varchar(128) default '',
  email varchar(128) NOT NULL default '',
  "reply-to" varchar(128) NOT NULL default '',
  bcc varchar(128) NOT NULL default '',
  signature text NOT NULL default '',
  html_signature tinyint NOT NULL default '0'
);
CREATE INDEX IF NOT EXISTS ix_identities_user_id ON identities(user_id, del);

CREATE TABLE IF NOT EXISTS searches (
  search_id integer NOT NULL PRIMARY KEY,
  user_id integer NOT NULL
    REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  "type" smallint NOT NULL DEFAULT '0',
  name varchar(128) NOT NULL,
  data text NOT NULL
);

CREATE TABLE IF NOT EXISTS session (
  sess_id varchar(128) NOT NULL PRIMARY KEY,
  expires_at datetime NOT NULL default '0000-00-00 00:00:00',
  ip varchar(40) NOT NULL default '',
  vars text NOT NULL
);

CREATE TABLE IF NOT EXISTS collected_addresses (
  address_id integer NOT NULL PRIMARY KEY,
  user_id integer NOT NULL
    REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  changed datetime NOT NULL default '0000-00-00 00:00:00',
  name varchar(255) NOT NULL default '',
  email varchar(255) NOT NULL,
  "type" integer NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_collected_addresses_user_id ON collected_addresses(user_id, "type", email);

CREATE TABLE IF NOT EXISTS responses (
  response_id integer NOT NULL PRIMARY KEY,
  user_id integer NOT NULL
    REFERENCES users (user_id) ON DELETE CASCADE ON UPDATE CASCADE,
  name varchar(100) NOT NULL,
  body text NOT NULL,
  html tinyint NOT NULL default '0'
);
