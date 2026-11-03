# -*- coding: utf-8 -*-
"""
Bridges the bot's CfgFactory/Config objects and the web interface.

Two value formats are used:
  * UI values      - what the web editor loads and saves. Roles and channels are referenced by id
                     (as strings, discord ids do not fit in a JS number).
  * export values  - Config.readable(): roles and channels by name, the same JSON the original
                     PUBobot2 web interface imported/exported, so old .cfg files keep working.
Both are accepted on save/import; everything is converted to the strings the Variable.validate()
methods expect.
"""
import re

from core.cfg_factory import (
	Variable, StrVar, EmojiVar, TextVar, OptionVar, BoolVar, IntVar, SliderVar, RoleVar, MemberVar,
	TextChanVar, DurationVar, VariableTable
)

TYPE_NAMES = [
	# order matters: subclasses first
	(VariableTable, 'table'),
	(SliderVar, 'slider'),
	(EmojiVar, 'emoji'),
	(StrVar, 'str'),
	(TextVar, 'text'),
	(OptionVar, 'option'),
	(BoolVar, 'bool'),
	(IntVar, 'int'),
	(RoleVar, 'role'),
	(MemberVar, 'member'),
	(TextChanVar, 'channel'),
	(DurationVar, 'duration'),
]


class ConfigError(Exception):
	def __init__(self, errors: dict):
		super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
		self.errors = errors


def var_type(v: Variable) -> str:
	for cls, name in TYPE_NAMES:
		if isinstance(v, cls):
			return name
	return 'str'


def var_schema(v: Variable) -> dict:
	kind = var_type(v)
	d = dict(
		name=v.name,
		display=v.display,
		description=v.description,
		section=v.section,
		type=kind,
		nullable=not v.notnull and kind != 'table',
		default=_default(v),
	)
	if kind == 'option':
		d['options'] = list(v.options)
	elif kind == 'slider':
		d.update(min=v.min_val, max=v.max_val, unit=v.unit)
	elif kind == 'table':
		d['columns'] = [var_schema(c) for c in v.variables.values()]
		d['blank'] = {k: _plain(c, val) for k, val in (v.blank or {}).items() for c in [v.variables[k]]}
	return d


def factory_schema(factory) -> dict:
	return dict(
		name=factory.name,
		display=factory.display,
		sections=list(factory.sections or []),
		variables=[var_schema(v) for v in factory.variables.values()],
	)


def _plain(v: Variable, value):
	""" Readable form of a raw (database) value, for defaults. """
	if value is None:
		return None
	if isinstance(v, (RoleVar, TextChanVar, MemberVar)):
		return str(value)
	if isinstance(v, VariableTable):
		return [{k: _plain(v.variables[k], val) for k, val in row.items()} for row in value]
	return v.readable(value)


def _default(v: Variable):
	try:
		return _plain(v, v.default)
	except Exception:
		return None


def ui_value(v: Variable, obj):
	""" Wrapped config attribute -> UI value """
	if obj is None:
		return None
	if isinstance(v, (RoleVar, TextChanVar, MemberVar)):
		return str(obj.id)
	if isinstance(v, VariableTable):
		return [{k: ui_value(v.variables[k], val) for k, val in row.items()} for row in obj]
	return v.readable(obj)


def ui_values(cfg) -> dict:
	return {name: ui_value(v, getattr(cfg, name)) for name, v in cfg._factory.variables.items()}


def export_values(cfg) -> dict:
	return cfg.readable()


_HMS = re.compile(r"^(\d+):(\d{1,2}):(\d{1,2})$")


def to_input(v: Variable, value):
	""" Any JSON value -> the string (or list) that Variable.validate() expects. """
	if isinstance(v, VariableTable):
		if value is None:
			return []
		if not isinstance(value, list):
			raise ValueError("Must be a list of rows.")
		rows = []
		for row in value:
			if not isinstance(row, dict):
				raise ValueError("Each row must be an object.")
			unknown = set(row) - set(v.variables)
			if unknown:
				raise ValueError(f"Unknown column(s): {', '.join(sorted(unknown))}.")
			rows.append({k: to_input(col, row.get(k)) for k, col in v.variables.items()})
		return rows

	if value is None:
		return 'none' if isinstance(v, BoolVar) else None
	if isinstance(value, bool):
		return 'on' if value else 'off'
	if isinstance(value, float) and value.is_integer():
		value = int(value)
	value = str(value)

	if isinstance(v, DurationVar):
		value = value.strip()
		if m := _HMS.match(value):
			h, mi, s = (int(i) for i in m.groups())
			return f"{h * 3600 + mi * 60 + s}s"
		if value.isdigit():
			return f"{value}s"
	elif isinstance(v, (IntVar, SliderVar)):
		value = value.strip()
	return value


def error_text(e: Exception) -> str:
	return getattr(e, 'message', None) or str(e) or e.__class__.__name__


async def check(factory, data: dict, guild) -> dict:
	""" Validate every field; returns {name: input value} or raises ConfigError with all field errors. """
	if not isinstance(data, dict):
		raise ConfigError({'_': "Config must be a JSON object."})
	errors, inputs = {}, {}
	for key, value in data.items():
		v = factory.variables.get(key)
		if v is None:
			errors[key] = "Unknown variable."
			continue
		try:
			inputs[key] = to_input(v, value)
			obj = await v.wrap(await v.validate(inputs[key], guild), guild)
			v.verify(obj)
		except Exception as e:
			errors[key] = error_text(e)
	if errors:
		raise ConfigError(errors)
	return inputs


async def apply(cfg, data: dict, guild) -> None:
	inputs = await check(cfg._factory, data, guild)
	if inputs:
		try:
			await cfg.update(inputs)
		except Exception as e:
			raise ConfigError({'_': error_text(e)})


def default_input(v: Variable):
	return _default(v)
