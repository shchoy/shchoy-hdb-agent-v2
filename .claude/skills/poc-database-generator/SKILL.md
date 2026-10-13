---
name: "poc-database-generator"
description: "create a database based on the the files in /poc-data/database folder"
---

Ask me the database stack to use (Postgres, MySQL, SQLite, LanceDB, DuckDB, etc.). If not given, default to SQLite in-memory database.

Create the database based on the files in /poc-data/database folder. Create the tables, indexes, and foreign keys as needed. Populate the tables with the data from the CSV or JSON files.

Create a database documentation file in /poc-data/_database.md that describes the tables, columns, indexes, and foreign keys. Include a sample query for each table. Include database schema diagram.

## Input
/poc-data/database folder