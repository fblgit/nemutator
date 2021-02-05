cfg = {
    'app': os.environ.get('CFG_APP', 'NEMUTATOR'),
    'web_port': int(os.environ.get('WEB_PORT', 8765)),
    'kube_cfg': os.environ.get('KUBE_CFG', '/Users/mrv/.kube/config')
}
