-- Runs once, on the first start of an empty database volume.
-- Both need UTF-8 encoding, but they disagree on collation: Jira recommends
-- 'C', while Confluence rejects 'C' at setup ("collation 'C' is not
-- supported") and needs a UTF-8 locale.

CREATE USER jira WITH PASSWORD 'jira';
CREATE DATABASE jira WITH OWNER jira ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;

CREATE USER confluence WITH PASSWORD 'confluence';
CREATE DATABASE confluence WITH OWNER confluence ENCODING 'UTF8' LC_COLLATE 'en_US.utf8' LC_CTYPE 'en_US.utf8' TEMPLATE template0;
