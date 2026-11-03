# -*- coding: utf-8 -*-
import sys
import os
import datetime
from collections import deque
from threading import Thread
from multiprocessing import Queue

from core.config import cfg, data_path

# An interactive console is only started when attached to a terminal
# (`docker attach` / running by hand). Under docker compose stdin is closed.
INTERACTIVE = sys.stdin is not None and sys.stdin.isatty()

if INTERACTIVE:
	import rlcompleter  # noqa: F401 - this does python autocomplete by tab
	try:
		import readline
	except ModuleNotFoundError:  # windows support
		import pyreadline as readline
else:
	readline = None

LogLevelToInt = {
	'CHAT': 0,
	'DEBUG': 1,
	'COMMANDS': 2,
	'INFO': 3,
	'ERRORS': 4,
	'NOTHING': 5
}


class Log:

	def __init__(self):
		self.file = open(data_path("logs", datetime.datetime.now().strftime("log_%Y-%m-%d_%H-%M.txt")), 'w', encoding='utf-8')
		self.loglevel = LogLevelToInt.get(cfg.LOG_LEVEL, 3)
		self.recent = deque(maxlen=500)  # shown in the web interface

	@staticmethod
	def display(string):
		# Have to do this encoding/decoding because python fails to encode some symbols by default
		encoding = sys.stdout.encoding or 'utf-8'
		string = string.encode(encoding, 'ignore').decode(encoding)

		if readline is not None:
			# Save user input line, print string and then user input line
			line_buffer = readline.get_line_buffer()
			sys.stdout.write("\r\n\033[F\033[K" + string + '\r\n>' + line_buffer)
		else:
			sys.stdout.write(string + "\n")
		sys.stdout.flush()

	def log(self, data, log_level):
		string = "{}|{}> {}".format(
			datetime.datetime.now().strftime("%d.%m.%Y (%H:%M:%S)"),
			log_level,
			str(data))
		self.display(string)
		self.recent.append(string)
		self.file.write(string + '\n')
		self.file.flush()

	def close(self):
		self.file.close()

	def chat(self, data):
		if self.loglevel <= 0:
			self.log(data, 'CHAT')

	def debug(self, data):
		if self.loglevel <= 1:
			self.log(data, 'DEBUG')

	def command(self, data):
		if self.loglevel <= 2:
			self.log(data, 'COMMANDS')

	def info(self, data):
		if self.loglevel <= 3:
			self.log(data, 'INFO')

	def error(self, data):
		if self.loglevel <= 4:
			self.log(data, 'ERROR')


def user_input():
	readline.parse_and_bind("tab: complete")
	while 1:
		try:
			input_cmd = input('>')
		except EOFError:
			return
		user_input_queue.put(input_cmd)


def terminate():
	global alive
	alive = False


alive = True
log = Log()
user_input_queue = Queue()

# Init user console
if INTERACTIVE:
	thread = Thread(target=user_input, name="user_input")
	thread.daemon = True
	thread.start()
