import logging
from nemutator_cfg import cfg
from nemutator.webhook import start_server

log = logging.getLogger('NEMUTATOR')
log.addHandler(logging.StreamHandler())
log.setLevel(logging.DEBUG)

if __name__ == '__main__':
    start_server(cfg)