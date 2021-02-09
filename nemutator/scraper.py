from nemutator.kube import K8

def scrape(config):
    k8_handler = K8(config['kube_cfg'])
    workload = k8_handler.load_data()
    k8_handler.pod_scrape_metrics()
    k8_handler.deployment_scrape_metrics()
    k8_handler.export_map()
