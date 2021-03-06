#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
This is a skeleton file that can serve as a starting point for a Python
console script. To run this script uncomment the following lines in the
[options.entry_points] section in setup.cfg:

    console_scripts =
         fibonacci = nlpia_bot.skeleton:run

Then run `python setup.py install` which will install the command `fibonacci`
inside your current environment.
Besides console scripts, the header (i.e. until _logger...) of this file can
also be used as template for Python modules.

Note: This skeleton file can be safely removed if not needed!

```bash
$ bot -b 'pattern,parul' -vv -p --num_top_replies=1
YOU: Hi
bot: Hello!
YOU: Looking good!
```
"""
import collections.abc
import importlib
import json
import logging
import os

import numpy as np
import pandas as pd

from nlpia_bot import constants
from nlpia_bot.constants import DATA_DIR
from nlpia_bot.scores.quality_score import QualityScore


__author__ = "see AUTHORS.md and README.md: Travis, Nima, Erturgrul, Aliya, Xavier, Maria, Hobson, ..."
__copyright__ = "Hobson Lane"
__license__ = "The Hippocratic License (MIT + *Do No Harm*, see LICENSE.txt)"


log = logging.getLogger(__name__)


BOT = None


def normalize_replies(replies=''):
    """ Make sure a list of replies includes score and text

    >>> normalize_replies(['hello world'])
    [(1e-10, 'hello world')]
    """
    if isinstance(replies, str):
        replies = [(1e-10, replies)]
    elif isinstance(replies, tuple) and len(replies, 2) and isinstance(replies[0], float):
        replies = [(replies[0], str(replies[1]))]
    # TODO: this sorting is likely unnecessary, redundant with sort happening within CLIBot.reply()
    return sorted([
        ((1e-10, r) if isinstance(r, str) else tuple(r))
        for r in replies
    ], reverse=True)


class CLIBot:
    """ Conversation manager intended to interact with the user on the command line, but can be used by other plugins/

    >>> CLIBot(bots='parul,pattern'.split(','), num_top_replies=1, semantics=1.0).reply('Hi')
    'Hello!'
    """
    bot_names = []
    bot_modules = []
    bots = []

    def __init__(
            self,
            bots=constants.DEFAULT_BOTS,
            num_top_replies=None,
            **quality_kwargs):
        if not isinstance(bots, collections.Mapping):
            bots = dict(zip(bots, [None] * len(bots)))
        for bot_name, bot_kwargs in bots.items():
            bot_kwargs = {} if bot_kwargs is None else dict(bot_kwargs)
            self.add_bot(bot_name, **bot_kwargs)
        self.num_top_replies = constants.DEFAULT_CONFIG['num_top_replies'] if num_top_replies is None else min(
            max(int(num_top_replies), 1), 10000)
        self.repliers = [bot.reply if hasattr(bot, 'reply') else bot for bot in self.bots if bot is not None]
        log.warn(f'Loaded bots: {self.repliers}')
        self.quality_score = QualityScore(**quality_kwargs)

    def add_bot(self, bot_name, **bot_kwargs):
        bot_name = bot_name if bot_name.endswith('_bots') else f'{bot_name}_bots'
        log.info(f'Adding bot named {bot_name}')
        self.bot_names.append(bot_name)
        bot_module = importlib.import_module(f'nlpia_bot.skills.{bot_name}')
        new_modules, new_bots = [], []
        if bot_module.__class__.__name__ == 'module':
            module_vars = tuple(vars(bot_module).items())
            for bot_class in (c for n, c in module_vars if n.endswith('Bot') and callable(getattr(c, 'reply', None))):
                log.info(f'Adding a Bot class {bot_class} from module {bot_module}...')
                new_bots.append(bot_class(**bot_kwargs))
                new_modules.append(bot_module)
        else:
            log.warning(f'FIXME: add feature to allow import of specific bot classes like "nlpia_bot.skills.{bot_name}"')
        self.bots.extend(new_bots)
        self.bot_modules.extend(new_modules)
        return new_bots

    def log_reply(self, statement, reply):
        history_path= os.path.join(constants.DATA_DIR, 'history.json')
        try:
            history = list()
            with open(history_path, 'r') as f:
                history = json.load(f)
        except IOError as e:
            log.error(str(e))
            with open(history_path, 'w') as f:
                f.write('[]')
        except json.JSONDecodeError as e:
            log.error(str(e))
            log.info('Saving history.json contents to history.json.swp before overwriting')
            with open(history_path, 'r') as f:
                data = f.read()
            with open(history_path + '.swp', 'w') as f:
                f.write(data)
        history.append(['user', statement])
        history.append(['bot', reply])
        with open(history_path, 'w') as f:
            json.dump(history, f)

    def reply(self, statement=''):
        ''' Collect replies from from loaded bots and return best reply (str). '''
        log.info(f'statement={statement}')
        replies = []
        # Collect replies from each bot.
        for replier in self.repliers:
            bot_replies = []
            try:
                bot_replies = replier(statement)
            except Exception as e:
                log.error(f'Error trying to run {replier.__self__.__class__}.{replier.__name__}("{statement}")')
                log.error(str(e))
                try:
                    log.debug(repr(replier))
                    bot_replies = normalize_replies(replier.reply(statement))
                except AttributeError as e:
                    log.warning(str(e))
                except Exception as e:
                    log.error(str(e))
            bot_replies = normalize_replies(bot_replies)
            replies.extend(bot_replies)

        # Weighted random selection of reply from those with top n confidence scores 
        if len(replies):
            log.info(f'Found {len(replies)} suitable replies, limiting to {self.num_top_replies}...')
            replies = self.quality_score.update_replies(replies, statement)
            replies = sorted(replies, reverse=True)[:self.num_top_replies]
            
            confidences, texts = list(zip(*replies))
            conf_sums = np.cumsum(confidences)
            roll = np.random.rand() * conf_sums[-1]
            
            for i, threshold in enumerate(conf_sums):
                if roll < threshold:
                    reply = texts[i]
                    self.log_reply(statement, reply)
                    return reply

        # TODO: np.choice from list of more friendly random unknown error replies...
        reply = "Sorry, something went wrong. Not sure what to say..."
        self.log_reply(statement, reply)
        return reply


def run_bot():
    global BOT
    if BOT is None:
        BOT = CLIBot(
            bots=constants.args.bots,
            num_top_replies=constants.args.num_top_replies,
            semantics=constants.args.semantics,
            sentiment=constants.args.sentiment,
            spell=constants.args.spell)
    if constants.args.persist:
        print('Type "quit" or "exit" to end the conversation...')

    log.debug(f'FINAL PROCESSED ARGS: {vars(constants.args)}')
    return BOT


def cli(args):
    global BOT
    BOT = run_bot() if BOT is None else BOT
    state = {}
    statements = []
    user_statement = ' '.join(args.words)
    statements.append(dict(user=user_statement, bot=None, **state))
    args.persist = args.persist or not len(user_statement)
    for i in range(constants.MAX_TURNS if args.persist else 0):
        if user_statement.lower().strip() in constants.EXIT_COMMANDS:
            break
        if user_statement:
            log.info(f"Computing a reply to {user_statement}...")
            # state = BOT.reply(statement, **state)
            # print(BOT)
            # print(type(BOT))
            bot_statement = BOT.reply(user_statement)
            statements[-1]['bot'] = bot_statement
            print(f"{args.nickname}: {bot_statement}")
        if args.persist or not user_statement:
            user_statement = input("YOU: ")
            statements.append(dict(user=user_statement, bot=None, **state))
        else:
            break
    return pd.DataFrame(statements)


def main():
    global BOT
    BOT = run_bot() if BOT is None else BOT
    # args = constants.parse_argv(argv=sys.argv)
    statements = cli(constants.args)
    if constants.args.loglevel >= 50:
        return
    return statements


if __name__ == "__main__":
    statements = main()
