#!/usr/bin/python3

#
# Script for muting threads in notmuch.
# The idea is that there's a "command" tag which you apply manually in the mail
# client. Then there's a "result" tag applied by this script, and you then
# configure the mail client to hide messages with that tag.
#
# Muting is propagated down the threads, but this is interrupted if someone CC's
# me on a thread that I wasn't formerly CC'd on, or To's me on a thread I wasn't
# To'd on.
#
# This needs to be run by hand after importing message into notmuch, but I think
# there's a hooks feature that could automate this.
#
# Note this script crashes at the end due to the notmuch library being kinda
# fucked. As far as I can tell this is harmless. I tried to just ignore SIGABRT
# but it still SIGABRTed, I dunno maybe I got that wrong.
#

import argparse
import collections
import enum
import os
import signal

import notmuch


MUTE_CMD_TAG = 'mute-thread'
MUTED_TAG = 'thread-muted'
# Internal tag to help avoid reprocessing zillions of threads.
PROCESSED_TAG = 'mute-processed'

def verbose_print(*args):
	if VERBOSE:
		print(*args)

class Addressed(enum.IntEnum):
	NONE = 0
	CC = 1
	TO = 2

	@classmethod
	def from_msg(cls, msg):
		if EMAIL in msg.get_header('To'):
			return cls.TO
		elif EMAIL in msg.get_header('Cc'):
			return cls.CC
		else:
			return cls.NONE


def print_thread(msg, nest_level=0):
	if MUTE_CMD_TAG in msg.get_tags():
		tag_chars = 'M'
	elif MUTED_TAG in msg.get_tags():
		tag_chars = 'm'
	else:
		tag_chars = ' '

	addressed = Addressed.from_msg(msg)
	if addressed == Addressed.TO:
		tag_chars += 't'
	elif addressed == Addressed.CC:
		tag_chars += 'c'
	else:
		tag_chars += ' '

	verbose_print(f'{'  ' * nest_level}<{tag_chars}> {msg.get_header('Subject')}')
	for reply in msg.get_replies():
		print_thread(reply, nest_level + 1)


def apply_mute(msg, parent_muted, parent_addressed):
	"""
	Propagate the mute-thread "command" tag to the thread-muted "outut" tag.

	Pass in a thread that has the 'mute-thread' tag, it will recurse its
	replies.
	"""
	addressed = Addressed.from_msg(msg)

	# We don't check for PROCESSED_TAG here because we might need to
	# recurse past processed messages into unprocessed replies. The job of that
	# tag is just to let us completely exclude threads that don't have any
	# unprocessed messages in them.

	# Mute unconditionally if this specific message has the command tag.
	if MUTE_CMD_TAG in msg.get_tags():
		mute = True
	elif parent_muted:
		# Don't propagate further if it seems like someone deliberately
		# tried to summon me on the thread.
		if parent_addressed is None:
			# Thread root
			mute = False
		else:
			mute = addressed <= parent_addressed
	else:
		mute = False

	if mute:
		msg.add_tag(MUTED_TAG)
	msg.add_tag(PROCESSED_TAG)

	for reply in msg.get_replies():
		apply_mute(reply, mute, addressed)


if __name__ == '__main__':
	parser = argparse.ArgumentParser(description="Script for muting threads in notmuch.")
	parser.add_argument('--email', required=True, help="The email address to check for in To/Cc.")
	parser.add_argument('--db-path', required=True, help="Path to the notmuch database.")
	parser.add_argument('--verbose', action='store_true')
	parser.add_argument('--query-extra', default='',
						help='Notmuch query terms to apply. Only modify threads with matches for these terms')
	args = parser.parse_args()

	EMAIL = args.email
	VERBOSE = args.verbose

	query_string = f'tag:{MUTE_CMD_TAG} AND NOT tag:{PROCESSED_TAG} ' + args.query_extra

	# Need to secify path explicitly, otherwise it doesn't work if the database
	# path isn't explicit in notmuch-config.
	db = notmuch.Database(path=args.db_path,
						  mode=notmuch.Database.MODE.READ_WRITE)
	for thread in db.create_query(query_string).search_threads():
		print_thread(next(thread.get_messages()))
		verbose_print()
		verbose_print('muting...')
	# Must recreate the iterator each time due to the fucked up memory
	# management, otherwise the library will SIGABRT.
	for thread in db.create_query(query_string).search_threads():
		apply_mute(next(thread.get_messages()), parent_muted=False, parent_addressed=None)
		verbose_print()
		verbose_print()
	for thread in db.create_query(query_string).search_threads():
		print_thread(next(thread.get_messages()))
