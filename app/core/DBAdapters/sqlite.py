# -*- coding: utf-8 -*-
"""
SQLite adapter, for development and the demo server only (DB_URI=sqlite://path/to/file.db).
Production uses MySQL/MariaDB. Queries run synchronously, which is fine for a single developer.
"""
import asyncio
import sqlite3

from .common import *


class Types:
	bool = "INTEGER"
	int = "INTEGER"
	float = "REAL"
	str = "TEXT"
	text = "TEXT"
	dict = "TEXT"


table_blank = dict(tname=None, columns=[], primary_keys=[], foreign_keys=[])
column_blank = dict(cname=None, ctype=Types.str, notnull=False, unique=False, autoincrement=False, default=None)


class Adapter:
	loop: asyncio.AbstractEventLoop
	types = Types
	errors = Errors

	def __init__(self, db_address):
		self.path = db_address or ":memory:"
		self.conn = None

	async def connect(self):
		self.loop = asyncio.get_running_loop()
		self.conn = sqlite3.connect(self.path)
		self.conn.row_factory = lambda cur, row: {d[0]: v for d, v in zip(cur.description, row)}
		self.conn.isolation_level = None  # autocommit

	def _run(self, request, args=()):
		try:
			return self.conn.execute(request, tuple(args))
		except sqlite3.IntegrityError as e:
			raise IntegrityError() from e
		except sqlite3.OperationalError as e:
			raise OperationalError() from e
		except sqlite3.Error as e:
			raise DatabaseError() from e

	async def execute(self, request, args=()):
		return self._run(request.replace("%s", "?"), args).lastrowid

	async def fetchone(self, request, args=()):
		return self._run(request.replace("%s", "?"), args).fetchone()

	async def fetchall(self, request, args=()):
		return self._run(request.replace("%s", "?"), args).fetchall()

	def ensure_table(self, table):
		self.loop.run_until_complete(self._ensure_table(table))

	async def _ensure_table(self, table):
		table = {**table_blank, **table}
		existing = {r['name'] for r in self._run(f"PRAGMA table_info(`{table['tname']}`)").fetchall()}
		columns = [{**column_blank, **c} for c in table['columns']]
		if not existing:
			defs = []
			rowid = len(table['primary_keys']) == 1 and any(
				c['autoincrement'] and c['cname'] == table['primary_keys'][0] for c in columns)
			for c in columns:
				if rowid and c['cname'] == table['primary_keys'][0]:
					defs.append(f"`{c['cname']}` INTEGER PRIMARY KEY")  # auto-assigned like AUTO_INCREMENT
					continue
				d = f"`{c['cname']}` {c['ctype']}"
				if c['notnull'] and not c['autoincrement']:
					d += " NOT NULL"
				if c['default'] is not None:
					d += f" DEFAULT '{c['default']}'"
				defs.append(d)
			if table['primary_keys'] and not rowid:
				defs.append("PRIMARY KEY(" + ", ".join(f"`{k}`" for k in table['primary_keys']) + ")")
			self._run(f"CREATE TABLE `{table['tname']}` ({', '.join(defs)})")
			return
		for c in columns:
			if c['cname'] not in existing:
				d = f"`{c['cname']}` {c['ctype']}"
				if c['default'] is not None:
					d += f" DEFAULT '{c['default']}'"
				self._run(f"ALTER TABLE `{table['tname']}` ADD COLUMN {d}")

	async def select(self, columns, table, where=None, order_by=None, order_asc=False, limit=None, one=False):
		conditions = " WHERE " + " AND ".join(f"`{k}`=?" for k in where.keys()) if where else ''
		args = list(where.values()) if where else []
		cols = ", ".join(c if c == '*' else f"`{c}`" for c in columns)
		request = "SELECT {} FROM `{}`{}{}{}".format(
			cols, table, conditions,
			f" ORDER BY `{order_by}`" + (" ASC" if order_asc else " DESC") if order_by else "",
			f" LIMIT {int(limit)}" if limit else ""
		)
		cur = self._run(request, args)
		return cur.fetchone() if one else cur.fetchall()

	async def select_one(self, *args, **kwargs):
		return await self.select(*args, **kwargs, one=True)

	async def delete(self, table, where=None):
		conditions = " WHERE " + " AND ".join(f"`{k}`=?" for k in where.keys()) if where else ''
		self._run(f"DELETE FROM `{table}`{conditions}", list(where.values()) if where else [])

	@staticmethod
	def _insert_sql(columns, table, on_dublicate):
		verb = {"replace": "INSERT OR REPLACE", "ignore": "INSERT OR IGNORE"}.get(on_dublicate, "INSERT")
		return "{} INTO `{}` ({}) VALUES({})".format(
			verb, table, ", ".join(f"`{c}`" for c in columns), ", ".join("?" for _ in columns))

	async def insert(self, table, d, on_dublicate=None):
		return self._run(self._insert_sql(d.keys(), table, on_dublicate), list(d.values())).lastrowid

	async def update(self, table, d, keys=None):
		keys = keys or {}
		where = " WHERE " + " AND ".join(f"`{k}`=?" for k in keys) if keys else ""
		self._run(
			"UPDATE `{}` SET {}{}".format(table, ", ".join(f"`{k}`=?" for k in d), where),
			list(d.values()) + list(keys.values())
		)

	async def insert_many(self, table, it, on_dublicate=None):
		try:
			first, it = peek(iter(it))
		except StopIteration:
			return
		request = self._insert_sql(first.keys(), table, on_dublicate)
		for d in it:
			self._run(request, list(d.values()))

	async def close(self):
		self.conn.close()
