#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FragQ - a self-hosted fork of PUBobot2 (https://github.com/Leshaka/PUBobot2) with a web interface.
"""

import time
import signal
import asyncio
import traceback
import queue
from asyncio import sleep as asleep
from asyncio import iscoroutine

# A loop is created up front: the database adapter and config factories use it at import time.
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Load bot core
from core import config, console, database, locales, cfg_factory  # noqa: E402
from core.client import dc  # noqa: E402

log = console.log
log.info(f"FragQ v{config.__version__} starting.")

if not config.cfg.DC_BOT_TOKEN:
	log.error("DISCORD_BOT_TOKEN is not set. Fill it in .env and restart.")
	raise SystemExit(1)


async def connect_db(attempts=30):
	""" The database container may still be starting, retry for a while. """
	for attempt in range(1, attempts + 1):
		try:
			await database.db.connect()
			return
		except Exception as e:
			if attempt == attempts:
				raise
			log.info(f"Waiting for the database ({attempt}/{attempts}): {e.__cause__ or e}")
			await asleep(2)

loop.run_until_complete(connect_db())

# Load bot
import bot  # noqa: E402

# Load web server
if config.cfg.WS_ENABLE:
	from webui import webserver
	loop.run_until_complete(webserver.start())
else:
	webserver = False


# Gracefully exit on ctrl+c / docker stop
def shutdown(sig, frame):
	if not console.alive:
		return
	log.info("Shutdown signal received.")
	bot.save_state()
	console.terminate()


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


# Run commands from user console
async def run_console():
	try:
		cmd = console.user_input_queue.get(False)
	except queue.Empty:
		return

	log.info(cmd)
	try:
		x = eval(cmd)
		if iscoroutine(x):
			log.info(await x)
		else:
			log.info(str(x))
	except Exception as e:
		log.error("CONSOLE| ERROR: "+str(e))


# Background processes loop
async def think():
	for task in dc.events['on_init']:
		await task()

	# Loop runs roughly every 1 second
	while console.alive:
		frame_time = time.time()
		if console.INTERACTIVE:
			await run_console()
		for task in dc.events['on_think']:
			try:
				await task(frame_time)
			except Exception as e:
				log.error('Error running background task from {}: {}\n{}'.format(task.__module__, str(e), traceback.format_exc()))
		await asleep(1)

	# Exit signal received
	for task in dc.events['on_exit']:
		try:
			await task()
		except Exception as e:
			log.error('Error running exit task from {}: {}\n{}'.format(task.__module__, str(e), traceback.format_exc()))

	log.info("Waiting for connection to close...")
	await dc.close()

	if webserver:
		log.info("Closing web server.")
		await webserver.stop()
	log.info("Closing db.")
	await database.db.close()
	log.info("Closing log.")
	log.close()
	print("Exit now.")
	loop.stop()


async def run_discord():
	try:
		await dc.start(config.cfg.DC_BOT_TOKEN)
	except Exception as e:
		log.error(f"Discord connection failed: {e}")
		console.terminate()

# Login to discord
loop.create_task(think())
loop.create_task(run_discord())

log.info("Connecting to discord...")
loop.run_forever()
