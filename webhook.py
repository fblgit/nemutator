import time
import os
import logging
import base64
import requests as req
import json
import IPython
from pprint import pprint
from flask import Flask, request
from flask_restful import Resource, Api
import string
import jsonpatch
import base64
import kubernetes
from kubernetes.client.rest import ApiException
from prometheus_api_client import PrometheusConnect
from nemutator_cfg import cfg

PROMETHEUS_URL = os.environ.get('PROMETHEUS_URL', 'http://')
API_KEY = os.environ.get('API_KEY', 'mykey')

# Prometheus: we must define recording rules in order to enable
# "tell me my max cpu usage in the last X days for this deployment or even this pod"
# this we will do with AVG, but should be solved before set in a beta ground

log = logging.getLogger(str(cfg['app']))
log.addHandler(logging.StreamHandler())
log.setLevel(logging.DEBUG)

app = Flask(__name__)
api = Api(app)

def clean_cpu(cpu):
    if isinstance(cpu, str):
        if 'm' in cpu:
            cpu = float(f"0.{cpu[0:-1]}")
    elif isinstance(cpu, int):
        cpu = float(cpu)
    # should be float now
    return cpu

def get_bytes(mem, suffix='k'):
    for x in range(0, len(str(mem))):
        if str(mem)[x] in string.ascii_letters:
            suffix = str(mem).lower()[x]
            size = int(str(mem)[0:x])
            break
    if suffix == 'k' or suffix == 'kb' or suffix == 'kib':
        return size << 10
    elif suffix == 'm' or suffix == 'mi' or suffix == 'mib':
        return size << 20
    elif suffix == 'g' or suffix == 'gi' or suffix == 'gib':
        return size << 30

def get_mb(mem):
    return f'{float(int(mem)>>20)}Mi'


def query_prometheus(search, mode='deployment', nature='cpu'):
    #/api/v1/query?query=avg(rate(container_cpu_usage_seconds_total%7Bnamespace%3D%22jarvis%22%2Ccontainer%3D%22cast-service%22%7D%5B5d%5D))
    #prom_url = k.get_prometheus()
    prom = PrometheusConnect(url='http://prometheus.k.nutz.site', disable_ssl=True)
    if not prom:
        log.debug(f'[QUERY-PROMETHEUS] Prometheus is Disabled or not found by K8s Service')
        return False
    if nature not in ['cpu', 'mem']:
        log.error(f'[QUERY-PROMETHEUS] Nature {nature} not valid')
        return False
    if mode not in ['deployment', 'pod']:
        log.error(f'[QUERY-PROMETHEUS] Mode {mode} not valid')
        return False
    # compose the query:
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
            log.info(f'[QUERY-PROMETHEUS] {search} for {mode} and {nature} ({query_style}] not found results ({query})')
            return False
        result = 0
        if nature == 'cpu':
            # transform to something human ready
            # style is '350'm (cpu fractions as base 100 scale per core)
            result = int(float(value)*100000)
        if nature == 'mem':
            # transforms to something human ready
            # style is '350.44'mb
            result = round(float(value)/1024/1024, 2)
        results[query_style] = result
        log.debug(f'[QUERY-PROMETHEUS] {search} {mode} {nature} {query_style} results: {result}')
    if results['max'] > 0 and results['avg'] > 0 and results['min'] > 0:
        try:
            results['peak'] = round(((results['max'] - results['avg']) / results['avg']) * 100, 2)
            results['off']  = round(((results['avg'] - results['min']) / results['avg']) * 100, 2)
        except ZeroDivisionError:
            results['off']  = 0
            results['peak'] = 0
    else:
        results['peak'] = 0
        results['off'] = 0
    return results

class K8():
    def __init__(self, kube_config=cfg['kube_cfg']):
        kubernetes.config.load_kube_config(kube_config)
        self.v1 = kubernetes.client.CoreV1Api()
        self.prometheus = None
    
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
                        prom_url = f"http://{prom_ip}:{prom_port}"
                        self.prometheus = PrometheusConnect(url=prom_url, disable_ssl=True)
        return self.prometheus
            

'''
@app.route('/', defaults={'path': ''}, methods=['GET'])
@app.route('/<path:path>', methods=['GET'])
def def_get(path):
    headers = {
        'Host': 'cubo.local.io'
    }
    for x in request.headers:
        if x[0] == 'Host':
            continue
        headers[x[0]] = x[1]
    args = {}
    for x in request.args:
        args[x] = request.args[x]
    log.debug(f'[GET] to {path} >> H: {headers} >> A: {args}')
    return '', 200
'''

class MutatorHook(Resource):
    def post(self):
        headers = {
            'Host': 'cubo.local.io'
        }
        for x in request.headers:
            if x[0] == 'Host':
                continue
            headers[x[0]] = x[1]
        payload = json.loads(request.data)
        uid = payload['request']['uid']
        apiVersion = payload['apiVersion']
        payload = payload['request']['object']
        org_payload = json.loads(request.data)['request']['object']
        if payload.get('metadata', {}).get('annotations', {}).get('nemutator.io/skip-mutation', 'false') == 'true':
            log.info(f'[SKIP-MUTATE] by {uid} (200)')
            return {}, 200
        containers = payload.get('spec', {}).get('containers', False)
        #print(f'C >> {containers}')
        if containers:
            # containers are present
            RATIO_CPU = 5.0
            RATIO_MEM = 3.0
            for x in range(0, len(containers)):
                #print(f'Iterate Contaienrs {x}')
                container = containers[x]
                container_name = container.get('name', 'default')

                # RESOURCES (LIMITS/REQUESTS)
                if 'resources' in container:
                    requests = container['resources'].get('requests', {})
                    limits = container['resources'].get('limits', {})
                    old_resources = container['resources']
                    new_resources = {
                        'limits': {},
                        'requests': {}
                    }
                    cur_resources = {}
                    seek_limits = True
                    if limits.get('cpu', False):
                        cur_resources['limits_cpu'] = float(clean_cpu(limits['cpu']))
                        new_resources['limits']['cpu'] = limits['cpu']
                        seek_limits = False
                    if limits.get('memory', False):
                        cur_resources['limits_mem'] = float(get_bytes(limits['memory']))
                        new_resources['limits']['memory'] = limits['memory']
                        seek_limits = False
                    if requests.get('cpu', False):
                        cur_resources['request_cpu'] = float(clean_cpu(requests['cpu']))
                        new_resources['requests']['cpu'] = str(cur_resources['request_cpu'] / RATIO_CPU)
                        seek_limits = False
                    if requests.get('memory', False):
                        cur_resources['requests_mem'] = float(get_bytes(requests['memory']))
                        new_resources['requests']['memory'] = get_mb(cur_resources['requests_mem'] / RATIO_MEM)
                        seek_limits = False
                    # simulation
                    if seek_limits:
                        prometheus_metrics = {
                            'mem': query_prometheus('tuya-ws', nature='mem'),
                            'cpu': query_prometheus('tuya-ws', nature='cpu')
                        }
                        log.info(f"[RESOURCES] {container_name} PromAvgCPU: {prometheus_metrics['cpu']} PromMaxMem: {prometheus_metrics['mem']}")
                        log.info(f"[LIMITS] {container_name} CPU: {int(prometheus_metrics['cpu']['max'] * 1.33)}m max+33% & MEM: {int(prometheus_metrics['mem']['max'] * 1.33)}Mi max+33%")
                        log.info(f"[REQUESTS] {container_name} CPU: {int(prometheus_metrics['cpu']['avg'] * 1.1)}m (avg+10%) & MEM: {int(prometheus_metrics['mem']['avg'] * 1.10)}Mi (avg+10%)")
                        log.info(f"[DEVIATION] {container_name} CPU Peak: {prometheus_metrics['cpu']['peak']}% vs CPU Off: {prometheus_metrics['cpu']['off']}%")
                        log.info(f"[DEVIATION] {container_name} MEM Peak: {prometheus_metrics['mem']['peak']}% vs MEM Off: {prometheus_metrics['mem']['off']}%")
                        ## here we should replace the payload (if agreed with a formula)
                    log.info(f'[MUTATION-RESOURCES] {container_name} Rationed From {old_resources} to {new_resources}')
                    payload['spec']['containers'][x]['resources'] = new_resources
                    # should have rationed the L v R
        result = {}
        if org_payload != payload:
            patch = jsonpatch.make_patch(json.loads(request.data)['request']['object'], payload)
            if patch and uid:
                log.debug(f'[JSON-PATCH] {uid} >> {patch}')
                result = {
                    'apiVersion': apiVersion,
                    'kind': 'AdmissionReview',
                    'response': {
                        'uid': uid,
                        'allowed': True,
                        'patchType': 'JSONPatch',
                        'patch': base64.b64encode(str(patch).encode('utf-8')).decode('utf-8')
                    }
                }
                log.info(f'[PATCH] {uid} with {result}')
        #log.debug(f'[POST] to {path} >> H: {headers} >> D: {pprint(json.loads(request.data))}')
        return result, 200, {'Content-Type': 'application/json', 'Connection': 'close'}

api.add_resource(MutatorHook, '/mutate' )
k = K8()

if __name__ == '__main__':
    app.run(use_reloader=True, debug=True, port=cfg['web_port'], host='0.0.0.0', threaded=True, ssl_context=('cubo.crt', 'cubo.key'))