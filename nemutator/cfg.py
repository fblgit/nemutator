import os

cfg = {
    'app': os.environ.get('CFG_APP', 'NEMUTATOR'),
    'web_port': int(os.environ.get('WEB_PORT', 8765)),
    'kube_cfg': os.environ.get('KUBE_CFG', '/Users/mrv/.kube/config'),
    'redis': {
        'ip': '192.168.0.65',
        'db': 0,
    },
    'tower': {
        'enabled': True,
        'bootload': True,
        'label': 'nemu.io~1stats',
        'structure': 'podcpu_podmem_depcpu_depmem_replicas',
        'pod_interval': 120,
        'dep_interval': 600
    },
    'ssl': {
        'crt': 'cubo.crt',
        'key': 'cubo.key'
    }
}
