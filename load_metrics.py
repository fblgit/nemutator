import logging
from nemutator.scraper import *
from nemutator_cfg import cfg

log = logging.getLogger('NEMUTATOR')
log.addHandler(logging.StreamHandler())
log.setLevel(logging.DEBUG)

scrape(cfg)
