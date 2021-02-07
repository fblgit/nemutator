import time
import os
import logging
from kubernetes.client.rest import ApiException
from prometheus_api_client import PrometheusConnect
from nemutator_cfg import cfg
import IPython
import kubernetes
from pprint import pprint
#import scheduler

tower_cfg = cfg['tower']

log = logging.getLogger(f"{str(cfg['app'])}-TOWER")
log.addHandler(logging.StreamHandler())
log.setLevel(logging.INFO)

def query_prometheus(search, mode='node', nature='cpu'):
    #/api/v1/query?query=avg(rate(container_cpu_usage_seconds_total%7Bnamespace%3D%22jarvis%22%2Ccontainer%3D%22cast-service%22%7D%5B5d%5D))
    #prom_url = k.get_prometheus()
    prom = PrometheusConnect(url='http://prometheus.k.nutz.site', disable_ssl=True)
    if not prom:
        log.debug(f'[QUERY-PROMETHEUS] Prometheus is Disabled or not found by K8s Service')
        return False
    if nature not in ['cpu', 'mem']:
        log.error(f'[QUERY-PROMETHEUS] Nature {nature} not valid')
        return False
    if mode not in ['node', 'pod', 'deployment']:
        log.error(f'[QUERY-PROMETHEUS] Mode {mode} not valid')
        return False
    # compose the query:
    if mode == 'node':
        if nature == 'cpu':
            query = {
                'usage': '(1000 *  (count(node_cpu_seconds_total{instance=~"%s.+",mode="user"}) \
                - avg(sum by (mode)(irate(node_cpu_seconds_total{instance=~"%s.+",mode="idle"}[5m])))))' % (search, search),
                'total': '(1000 * (count(node_cpu_seconds_total{instance=~"%s.+",mode="user"})))' % (search)
            }
        if nature == 'mem':
            query = {
                'usage': 'node_memory_MemFree_bytes{instance=~"%s.+"}' % (search),
                'total': 'node_memory_MemTotal_bytes{instance=~"%s.+"}' % (search)
            }
        results = {}
        for query_mode in query.keys():
            value = prom.custom_query(query=query[query_mode])
            result = 0
            if len(value):
                value = value[0].get('value', [0, False])[-1]
                if not value:
                    log.debug(f'[QUERY-PROMETHEUS] {search} for {mode} and {nature} not found results ({query})')
                    return False
                if nature == 'mem':
                    result = int(value)
                if nature == 'cpu':
                    result = int(round(float(value), 0))
            log.debug(f'[QUERY-PROMETHEUS] {search} {mode} {nature} results: {result}')
            results[query_mode] = result
        results['available'] = results['total'] - results['usage']
        return results
    if mode == 'deployment':
        if nature == 'cpu':
            metric = 'container_cpu_usage_seconds_total'
            query = {
                'max': 'max(rate(%s{container="%s"}[3d]))' % (metric, search),
                'avg': 'avg(rate(%s{container="%s"}[3d]))' % (metric, search),
                'min': 'min(rate(%s{container="%s"}[3d]))' % (metric, search) 
            }
        elif nature == 'mem':
            metric = 'container_memory_max_usage_bytes'
            query = {
                'max': 'max(max_over_time(%s{container="%s"}[3d]))' % (metric, search),
                'avg': 'max(avg_over_time(%s{container="%s"}[3d]))' % (metric, search),
                'min': 'max(min_over_time(%s{container="%s"}[3d]))' % (metric, search)
            }
        results = {}
        for query_style in query.keys():
            value = prom.custom_query(query=query[query_style])
            if len(value):
                value = value[0].get('value', [0, False])[-1]
            if not value:
                log.debug(f'[QUERY-PROMETHEUS] {search} for {mode} and {nature} ({query_style}) not found results ({query})')
                return False
            result = 0
            if nature == 'cpu':
                # transform to something human ready
                # style is '350'm (cpu fractions as base 100 scale per core)
                result = round(float(value)*1000, 2)
            if nature == 'mem':
                # transforms to something human ready
                # style is '350.44'mb
                result = round(float(value)/1024/1024, 2)
            results[query_style] = result
            log.debug(f'[QUERY-PROMETHEUS] {search} {mode} {nature} {query_style} results: {result}')
        return results
    if mode == 'pod':
        if nature == 'cpu':
            metric = 'container_cpu_usage_seconds_total'
            query = {
                'max': 'max(rate(%s{pod="%s"}[3d]))' % (metric, search),
                'avg': 'avg(rate(%s{pod="%s"}[3d])>0)' % (metric, search),
                'min': 'min(rate(%s{pod="%s"}[3d])>0)' % (metric, search) 
            }
        elif nature == 'mem':
            metric = 'container_memory_max_usage_bytes'
            query = {
                'max': 'max(max_over_time(%s{pod="%s"}[3d]))' % (metric, search),
                'avg': 'max(avg_over_time(%s{pod="%s"}[3d]))' % (metric, search),
                'min': 'min(min_over_time(%s{pod="%s"}[3d]))' % (metric, search)
            }
        results = {}
        for query_style in query.keys():
            value = prom.custom_query(query=query[query_style])
            if len(value):
                value = value[0].get('value', [0, False])[-1]
            if not value:
                log.debug(f'[QUERY-PROMETHEUS] {search} for {mode} and {nature} ({query_style}) not found results ({query})')
                return False
            result = 0
            if nature == 'cpu':
                # transform to something human ready
                # style is '350'm (cpu fractions as base 100 scale per core)
                result = round(float(value)*1000, 2)
            if nature == 'mem':
                # transforms to something human ready
                # style is '350.44'mb
                result = round(float(value)/1024/1024, 2)
            results[query_style] = result
            log.debug(f'[QUERY-PROMETHEUS] {search} {mode} {nature} {query_style} results: {result}')
        return results

class UpdateElements():
    def __init__(self, kube_config=cfg['kube_cfg']):
        kubernetes.config.load_kube_config(kube_config)
        self.v1 = kubernetes.client.CoreV1Api()
        self.apps = kubernetes.client.AppsV1Api()
        self.nodes = {}
        self.pods = {}
        self.deployments = {}
        self.replicaset = {}
        self.reconciliation = 0

    def get_nodes_list(self):
        node_list = self.v1.list_node().to_dict()
        nodes = {}
        for node in node_list.get('items', []):
            node_name = node.get('metadata', {}).get('name', 'unknown')
            node_ip = '127.0.0.1'
            for address in node.get('addresses', []):
                if address.get('type', False) == 'InternalIP' and 'address' in address:
                    node_ip = address['address']
            if node not in nodes:
                nodes[node_name] = node_ip
        self.nodes = nodes
        return self.nodes
    
    def update_replicaset(self, name, namespace):
        replica = self.apps.read_namespaced_replica_set(name, namespace).to_dict()
        payload = {}
        replica_name = replica.get('metadata', {}).get('name', 'unknown')
        if replica.get('status', {}).get('replicas', False) and replica.get('status', {}).get('ready_replicas', False):
            payload['replicas'] = replica['status']['replicas']
            payload['replicas_ready']  = replica['status']['ready_replicas']
            payload['namespace'] = replica.get('metadata', {}).get('namespace', 'unknown')
        for owner in replica.get('metadata', {}).get('owner_references', []):
            if owner.get('kind', False) == 'Deployment' and owner.get('name', False):
                payload['owner'] = owner['name']
        payload['pods'] = []
        self.replicas[replica_name] = payload
        self.link_pod_rs_dep()
        return payload

    def get_replicaset_list(self):
        replicas_list = self.apps.list_replica_set_for_all_namespaces().to_dict()
        replicas  = {}
        for replica in replicas_list.get('items', []):
            payload = {}
            replica_name = replica.get('metadata', {}).get('name', 'unknown')
            if replica_name not in replicas:
                if replica.get('status', {}).get('replicas', False) and replica.get('status', {}).get('ready_replicas', False):
                    payload['replicas'] = replica['status']['replicas']
                    payload['replicas_ready']  = replica['status']['ready_replicas']
                    payload['namespace'] = replica.get('metadata', {}).get('namespace', 'unknown')
                    if replicas == 0:
                        continue
                else:
                    continue
                for owner in replica.get('metadata', {}).get('owner_references', []):
                    if owner.get('kind', False) == 'Deployment' and owner.get('name', False):
                        payload['owner'] = owner['name']
                payload['pods'] = []
                replicas[replica_name] = payload
        self.replicas = replicas
        return self.replicas

    def update_deployment(self, name, namespace):
        deployment = self.apps.read_namespaced_deployment(name, namespace).to_dict()
        payload = {}
        deployment_name = deployment.get('metadata', {}).get('name', 'unknown')
        payload['replicas'] = []
        payload['namespace'] = deployment.get('metadata', {}).get('namespace', 'unknown')
        self.deployments[deployment_name] = payload
        self.link_pod_rs_dep()
        return payload

    def get_deployment_list(self):
        deployments_list = self.apps.list_deployment_for_all_namespaces().to_dict()
        deployments = {}
        for deployment in deployments_list.get('items', []):
            payload = {}
            deployment_name = deployment.get('metadata', {}).get('name', 'unknown')
            if deployment_name not in deployments:
                payload['replicas'] = []
                payload['namespace'] = deployment.get('metadata', {}).get('namespace', 'unknown')
                deployments[deployment_name] = payload
                payload['metrics'] = self.deployments.get(deployment_name, {}).get('metics', {})
        self.deployments = deployments
        return self.deployments

    def update_pod(self, name, namespace):
        pod = self.v1.read_namespaced_pod(name, namespace).to_dict()
        payload = {}
        pod_name = pod.get('metadata', {}).get('name', 'unknown')
        payload['namespace'] = pod.get('metadata', {}).get('namespace', 'unknown')
        if pod.get('metadata', {}).get('owner_references', []) is not None:
            for owner in pod.get('metadata', {}).get('owner_references', []):
                if owner.get('kind', False) == 'ReplicaSet' and owner.get('name', False):
                    payload['owner'] = owner['name']
        payload['containers'] = []
        for container in pod.get('spec', {}).get('containers', []):
            payload['containers'].append(container.get('name', 'unknown'))
        if self.pods.get(pod_name, {}).get('deployment', False):
            payload['deployment'] = self.pods[pod_name]['deployment']
        self.pods[pod_name] = payload
        self.link_pod_rs_dep()
        return payload
    
    def get_pod_list(self):
        pods_list = self.v1.list_pod_for_all_namespaces().to_dict()
        pods = {}
        for pod in pods_list.get('items', []):
            payload = {}
            pod_name = pod.get('metadata', {}).get('name', 'unknown')
            if pod_name not in pods:
                payload['namespace'] = pod.get('metadata', {}).get('namespace', 'unknown')
                if pod.get('metadata', {}).get('owner_references', []) is not None:
                    for owner in pod.get('metadata', {}).get('owner_references', []):
                        if owner.get('kind', False) == 'ReplicaSet' and owner.get('name', False):
                            payload['owner'] = owner['name']
                payload['containers'] = []
                for container in pod.get('spec', {}).get('containers', []):
                    payload['containers'].append(container.get('name', 'unknown'))
                pods[pod_name] = payload
                if self.pods.get(pod_name, {}).get('deployment', False):
                    payload['deployment'] = self.pods[pod_name]['deployment']
                payload['metrics'] = self.pods.get(pod_name, {}).get('metrics', {})
        self.pods = pods
        return self.pods
    
    def link_pod_rs_dep(self):
        for pod in self.pods.keys():
            if self.pods[pod].get('owner', 'unknown') in self.replicas:
                if pod not in self.replicas[self.pods[pod]['owner']]['pods']:
                    if 'owner' in self.pods[pod]:
                        self.replicas[self.pods[pod]['owner']]['pods'].append(pod)
        for replica in self.replicas:
            if self.replicas[replica].get('owner', 'unknown') in self.deployments:
                if replica not in self.deployments[self.replicas[replica]['owner']]['replicas']:
                    self.deployments[self.replicas[replica]['owner']]['replicas'] = replica
                    self.deployments[self.replicas[replica]['owner']]['pods'] = self.replicas[replica]['pods']
                    for pod in self.replicas[replica]['pods']:
                        self.pods[pod]['deployment'] = self.replicas[replica]['owner']
        self.reconciliation = time.time()
        return self.reconciliation
    
    def clean_structure(self):
        for deployment in self.deployments:
            for pod in self.deployments[deployment]['pods']:
                if pod not in self.pods:
                    self.deployments[deployment]['pods'].pop(pod)
        for replica in self.replicas:
            for pod in self.replicas[replica]['pods']:
                if pod not in self.pods:
                    self.replicas[replica]['pods'].pop(pod)
    
    def load_data(self):
        log.info(f'[UPDATER] Loading Deployment..')
        self.get_deployment_list()
        log.info(f'[UPDATER] Loading ReplicaSet..')
        self.get_replicaset_list()
        log.info(f'[UPDATER] Loading Pod..')
        self.get_pod_list()
        log.info(f'[UPDATER] Cross-Reference Pod-ReplicaSet-Deployment..')
        self.link_pod_rs_dep()
        log.info(f'[UPDATER] Scrape Pod Metrics..')
        self.pod_scrape_metrics()
        log.info(f'[UPDATER] Scrape Deployment Metrics..')
        self.deployment_scrape_metrics()
        log.info(f'[UPDATER] Done')
        return {
            'deployments': self.deployments,
            'replicas': self.replicas,
            'pods': self.pods
        }
    
    def eventual_pod_refresh(self):
        self.get_pod_list()
        self.clean_structure()
        self.link_pod_rs_dep()
    
    def eventual_replica_refresh(self):
        self.get_replicaset_list()
        self.clean_structure()
        self.link_pod_rs_dep()
    
    def eventual_deployment_refresh(self):
        self.get_deployment_list()
        self.clean_structure()
        self.link_pod_rs_dep()

    def pod_scrape_metrics(self):
        for pod in self.pods.keys():
            payload = {
                'cpu': query_prometheus(pod, mode='pod', nature='cpu'),
                'mem': query_prometheus(pod, mode='pod', nature='mem')
            }
            if payload['cpu'] and payload['mem']:
                self.pods[pod]['metrics'] = payload
                log.debug(f'[SCRAPE-POD] {pod} >> {payload}')
    
    def deployment_scrape_metrics(self):
        for deployment in self.deployments.keys():
            payload = {
                'cpu': query_prometheus(deployment, mode='deployment', nature='cpu'),
                'mem': query_prometheus(deployment, mode='deployment', nature='mem')
            }
            if payload['cpu'] and payload['mem']:
                self.deployments[deployment]['metrics'] = payload
                log.debug(f'[SCRAPE-DEPLOYMENT] {deployment} >> {payload}')

    def workload_scrape_metrics(self):
        self.pod_scrape_metrics()
        self.deployment_scrape_metrics()

    def come_in(self):
        IPython.embed()


o = UpdateElements()
workload = o.load_data()
pprint(workload)
# TODO
# - add restful interface for the data
# - add scheduler to keep updated the data
# - add patch pod routine
# - add patch deployment routine