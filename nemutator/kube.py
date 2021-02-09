import json
import logging
import time
import kubernetes
from kubernetes.client.rest import ApiException
from nemutator.tools import get_bytes, clean_cpu
from nemutator.telemetry import query_prometheus


log = logging.getLogger('NEMUTATOR')

class K8():
    def __init__(self, kube_config):
        kubernetes.config.load_kube_config(kube_config)
        self.v1 = kubernetes.client.CoreV1Api()
        self.apps = kubernetes.client.AppsV1Api()
        self.nodes = {}
        self.pods = {}
        self.deployments = {}
        self.replicas = {}
        self.reconciliation = 0
        self.prometheus = None

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
        return self.get_replicaset_list(target=name, namespace=namespace)

    def get_replicaset_list(self, target=False, namespace=False):
        if target and namespace:
            replicas_list = {'items': [self.apps.read_namespaced_replica_set(target, namespace).to_dict()]}
        else:
            replicas_list = self.apps.list_replica_set_for_all_namespaces().to_dict()
        replicas  = {}
        for replica in replicas_list.get('items', []):
            payload = {}
            replica_name = replica.get('metadata', {}).get('name', 'unknown')
            if replica_name not in replicas:
                payload['replica'] = replica_name
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
                if target and namespace:
                    self.replicas[replica_name] = payload
                    return self.replicas[replica_name]
        self.replicas = replicas
        return self.replicas

    def update_deployment(self, name, namespace):
        return self.get_deployment_list(target=name, namespace=namespace)

    def get_deployment_list(self, target=False, namespace=False):
        if target and namespace:
            deployments_list = {'items': [self.apps.read_namespaced_deployment(target, namespace).to_dict()]}
        else:
            deployments_list = self.apps.list_deployment_for_all_namespaces().to_dict()
        deployments = {}
        for deployment in deployments_list.get('items', []):
            payload = {}
            deployment_name = deployment.get('metadata', {}).get('name', 'unknown')
            if deployment_name not in deployments:
                payload['replicas'] = []
                payload['namespace'] = deployment.get('metadata', {}).get('namespace', 'unknown')
                payload['deployment'] = deployment_name
                payload['metrics'] = self.deployments.get(deployment_name, {}).get('metics', {})
                deployments[deployment_name] = payload
            if target and namespace:
                self.deployments[deployment_name] = payload
                return payload
        self.deployments = deployments
        return self.deployments

    def update_pod(self, name, namespace):
        return self.get_pod_list(target=name, namespace=namespace)

    def get_pod_list(self, target=False, namespace=False):
        if target and namespace:
            pods_list = {'items', [self.v1.read_namespaced_pod(target, namespace).to_dict()]}
        else:
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
                            payload['replica'] = owner['name']
                payload['containers'] = []
                payload['requests'] = {
                    'cpu': [],
                    'memory': []
                }
                payload['limits'] = {
                    'cpu': [],
                    'memory': []
                }
                for container in pod.get('spec', {}).get('containers', []):
                    payload['containers'].append(container.get('name', 'unknown'))
                    if 'resources' in container:
                        for r_mode in container['resources']:
                            if r_mode in payload:
                                if container['resources'][r_mode] is None:
                                    continue
                                for r_k_mode in container['resources'][r_mode]:
                                    if r_k_mode in payload[r_mode]:
                                        if r_k_mode == 'cpu':
                                            cpu = clean_cpu(container['resources'][r_mode][r_k_mode], mode='prom')
                                            payload[r_mode][r_k_mode].append(cpu)
                                        if r_k_mode == 'memory':
                                            mem = get_bytes(container['resources'][r_mode][r_k_mode])
                                            payload[r_mode][r_k_mode].append(mem)
                payload['resources'] = {
                    'limits': {},
                    'requests': {}
                }
                for r_k_mode in payload['limits']:
                    if payload['limits'][r_k_mode]:
                        payload['resources']['limits'][r_k_mode] = sum(payload['limits'][r_k_mode])
                for r_k_mode in payload['requests']:
                    if payload['requests'][r_k_mode]:
                        payload['resources']['requests'][r_k_mode] = sum(payload['requests'][r_k_mode])
                if self.pods.get(pod_name, {}).get('deployment', False):
                    payload['deployment'] = self.pods[pod_name]['deployment']
                payload['metrics'] = self.pods.get(pod_name, {}).get('metrics', {})
                pods[pod_name] = payload
            if target and namespace:
                self.pods[pod_name] = pods[pod_name]
                return pod[pod_name]
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
                    resources = {
                        'limits': {
                            'cpu': 0,
                            'memory': 0,
                        },
                        'requests': {
                            'cpu': 0,
                            'memory': 0
                        }
                    }
                    for pod in self.replicas[replica]['pods']:
                        for r_mode in self.pods[pod]['resources']:
                            for r_k_mode in self.pods[pod]['resources'][r_mode]:
                                resources[r_mode][r_k_mode] += self.pods[pod]['resources'][r_mode][r_k_mode]
                        self.pods[pod]['deployment'] = self.replicas[replica]['owner']
                    self.replicas[replica]['resources'] = resources
                    self.deployments[self.replicas[replica]['owner']]['resources'] = self.replicas[replica]['resources']
                    self.deployments[self.replicas[replica]['owner']]['replica_pods'] =  self.replicas[replica]['replicas']
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
        log.info(f'[UPDATER] Done')
        return {
            'deployments': self.deployments,
            'replicas': self.replicas,
            'pods': self.pods
        }

    def load_metrics(self):
        log.info(f'[UPDATER] Scrape Pod Metrics..')
        self.pod_scrape_metrics()
        log.info(f'[UPDATER] Scrape Deployment Metrics..')
        self.deployment_scrape_metrics()

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

    def export_map(self):
        d = []
        r = []
        p = []
        for x in self.deployments:
            d.append(self.deployments[x])
        for x in self.pods:
            p.append(self.pods[x])
        for x in self.replicas:
            r.append(self.replicas[x])
        f = open('replica.json', 'w')
        f.write(json.dumps(r))
        f = open('deployments.json', 'w')
        f.write(json.dumps(d))
        f = open('pods.json', 'w')
        f.write(json.dumps(p))
        return d,r,p

    def get_prometheus(self, namespace='monitoring'):
        services = self.v1.list_namespaced_service(namespace=namespace).to_dict()
        if self.prometheus is None:
            self.prometheus = False
            for service in services.get('items', []):
                service_name = service.get('metadata', {}).get('name', False)
                if service_name in ['prometheus-kube-prometheus-prometheus']:
                    prom_ip = service.get('spec', {}).get('cluster_ip', False)
                    prom_port = service.get('spec', {}).get('ports', {})
                    if prom_port and prom_ip:
                        prom_port = prom_port[0]['port']
                        self.prometheus = f"http://{prom_ip}:{prom_port}"
        return self.prometheus
