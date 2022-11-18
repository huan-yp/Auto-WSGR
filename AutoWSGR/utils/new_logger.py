import json
import logging
import os
import sys
from typing import TextIO

import wandb


class LoggerWriter:
    def __init__(self, console: TextIO, file: TextIO):
        self.console = console
        self.file = file

    def write(self, message):
        self.console.write(message)
        self.file.write(message)

    def flush(self):
        self.console.flush()
        self.file.flush()


class Logger:
    def __init__(self, config):
        self.config = config
        self.console_logger = self._get_logger()

        # setup stats logging
        self.stats_save_path = os.path.join(config["results_save_dir"], "stats.json")
        self.stats = {}

        self.use_wandb = config["use_wandb"]

        if config["use_wandb"] and not config["evaluate"]:
            self.wandb_last_log_t = -1
            self._setup_wandb(config["results_save_dir"])  # will automatically create "wandb" subfolder

    def save_config(self, config):
        # write config file
        config_str = json.dumps(config, ensure_ascii=False, indent=4, sort_keys=True)
        with open(os.path.join(config["results_save_dir"], "config.json"), "w") as f:
            f.write(config_str)
        return config_str

    def _setup_wandb(self, directory_name):
        group_name = self.config['env']
        if 'map_name' in self.config['env_args']:
            group_name += '.' + self.config['env_args']['map_name']
        job_name = self.config['name'] + self.config.get('remark', '')

        wandb.init(project="pymarl-ext",
                   group=group_name,
                   job_type=job_name,
                   dir=directory_name,
                   reinit=True,
                   config=self.config)

    def log_info(self, string):
        self.console_logger.info(string)

    def log_stat(self, key, value, t, tag='train'):
        if tag not in self.stats:
            self.stats[tag] = {}
        if key not in self.stats[tag]:
            self.stats[tag][key] = []
        self.stats[tag][key].append((t, float(value)))

        if self.use_wandb:
            if self.wandb_last_log_t != t:
                wandb.log({"timesteps": self.wandb_last_log_t})
            wandb.log(f"{tag}/{key}", commit=False)
            self.wandb_last_log_t = t

    def _get_logger(self) -> logging.Logger:
        self.log_file_path = os.path.join(self.config["results_save_dir"], "console.log")
        self.log_file = open(self.log_file_path, 'a')

        sys.stdout = LoggerWriter(sys.stdout, self.log_file)
        sys.stderr = LoggerWriter(sys.stderr, self.log_file)

        logger = logging.getLogger()
        logger.handlers = []
        ch_formatter = logging.Formatter('[%(levelname)s %(asctime)s %(name)s] %(message)s', '%H:%M:%S')
        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(ch_formatter)
        logger.addHandler(ch)
        logger.setLevel('DEBUG')

        return logger
