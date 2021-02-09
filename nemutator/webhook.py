import base64
import json
import logging
import time
import jsonpatch
from flask import Flask, request
from flask_restful import Resource, Api
from nemutator.tools import get_mb, get_bytes, clean_cpu
from nemutator.telemetry import query_prometheus
from nemutator.tpdb import R
from nemutator.cfg import cfg

log = logging.getLogger('NEMUTATOR')

class MutatorHook(Resource):
    def __init__(self):
        self.tpdb = R()
        self.tpdb.conn(cfg)
        self.selectors_list = self.tpdb.get_selectors_replace()
        self.patch_folder = './patches'
        self.mutation_log = f'{self.patch_folder}/nemutator-rollback.json'

    def post(self):
        payload = json.loads(request.data)
        operation_mode = payload.get('request', {}).get('operation', False)
        uid = payload.get('request', {}).get('uid', 'no-uid')
        apiVersion = payload.get('apiVersion', 'NoApiVersion')
        payload = payload.get('request', {}).get('object', {})
        # Reduce the Payload to the object itself, simpler patch manipulation
        org_payload = json.loads(request.data).get('request', {}).get('object', {})
        object_kind = payload.get('kind', 'UnknownKind')
        log.debug(f'[NEMUTATOR] {uid} >> {operation_mode} >> {object_kind} (BEGIN)')
        skip_modes = []
        if payload.get('metadata', {}).get('annotations', {}).get('nemutator.io/skip-mutation', 'false') == 'true':
            log.info(f'[SKIP-MUTATE] ({operation_mode}) by {uid} (200)')
            return {}, 200
        if payload.get('metadata', {}).get('annotations', {}).get('nemutator.io/skip', False):
            for mode in payload.get('metadata', {}).get('annotations', {}).get('nemutator.io/skip', '').split(' '):
                if mode not in skip_modes:
                    skip_modes.append(mode)
                    log.info(f'[SKIP-{mode.upper()}] ({operation_mode}) by {uid} by skip:{mode} annotation')
        mutations = []
        object_name = 'NO_NAME_YET'
        if object_kind == 'Deployment':
            # SELECTOR tied to Labels
            deployment_name = payload.get('metadata', {}).get('name', 'unknown')
            object_name = deployment_name
            if payload.get('spec', {}).get('selector', {}) and 'selector' not in skip_modes:
                for s_key in org_payload['spec']['selector']:
                    if s_key in self.selectors_list:
                        s_s_key = f'nemu_selector_label_{s_key}'
                        n_s_key = self.tpdb.get_selector(s_s_key)
                        s_s_value = f'nemu_selector_label_value_{s_key}'
                        n_s_value = self.tpdb.get_selector(s_s_value)
                        if n_s_key:
                            del payload['spec']['selector'][s_key]
                            if s_s_value:
                                payload['spec']['selector'][n_s_key] = n_s_value
                                log.info(f'[MUTATE-SELECTOR] ({operation_mode}) {deployment_name} Mutated SELECTOR Key+Value of {s_key} to {n_s_key}:{n_s_value}')
                            else:
                                payload['spec']['selector'][n_s_key] = org_payload['spec']['selector'][s_key]
                                log.info(f'[MUTATE-SELECTOR] ({operation_mode}) {deployment_name} Mutated SELECTOR OnlyKey {s_key} to {n_s_key}')
                        if not n_s_key and n_s_value:
                            payload['spec']['selector'][s_key] = n_s_value
                            log.info(f'[MUTATE-SELECTOR] ({operation_mode}) {deployment_name} Mutated SELECTOR OnlyValue {s_key} to {n_s_value}')

            print(payload)
        elif object_kind == 'Pod' and operation_mode in ['UPDATE', 'CREATE']:
            containers = payload.get('spec', {}).get('containers', False)
            container_name = payload.get('metadata', {}).get('name', 'default_name')
            object_name = container_name
            # LABELS
            if payload.get('metadata', {}).get('labels', {}) and 'labels' not in skip_modes:
                for label in org_payload['metadata']['labels'].keys():
                    if 'nemu_label_' not in label[0:11]:
                        continue
                    result = self.tpdb.get_label(label)
                    if result:
                        old_value = payload['metadata']['labels'][label]
                        del payload['metadata']['labels'][label]
                        payload['metadata']['labels'][result] = old_value
                        log.info(f'[MUTATE-LABEL] ({operation_mode}) {container_name} Mutated LABEL Key {label} to {result}')
            if payload.get('metadata', {}).get('labels', {}) and 'labels' not in skip_modes:
                for label in payload['metadata']['labels'].keys():
                    if 'nemu_label_value_' not in payload['metadata']['labels'][label][0:17]:
                        continue
                    result = self.tpdb.get_label(payload['metadata']['labels'][label])
                    if result:
                        if payload['metadata']['labels'][label] != result:
                            payload['metadata']['labels'][label] = result
                            log.info(f'[MUTATE-LABEL] ({operation_mode}) {container_name} Mutated LABEL Value {label} to {result}')
                            if 'labels' not in mutations:
                                mutations.append('labels')
            # ANNOTATIONS
            if payload.get('metadata', {}).get('annotations', {}) and 'annotations' not in skip_modes:
                for annotation in org_payload['metadata']['annotations'].keys():
                    if 'nemu_anno_' not in annotation[0:10]:
                        continue
                    result = self.tpdb.get_annotation(annotation)
                    if result:
                        old_value = payload['metadata']['annotations'][annotation]
                        del payload['metadata']['annotations'][annotation]
                        payload['metadata']['annotations'][result] = old_value
                        log.info(f'[MUTATE-ANNOTATION] ({operation_mode}) {container_name} Mutated ANNOTATION Key {annotation} to {result}')
            if payload.get('metadata', {}).get('annotations', {}) and 'annotations' not in skip_modes:
                for annotation in payload['metadata']['annotations'].keys():
                    if 'nemu_anno_value_' not in payload['metadata']['annotations'][annotation][0:16]:
                        continue
                    result = self.tpdb.get_annotation(payload['metadata']['annotations'][annotation])
                    if result:
                        if payload['metadata']['annotations'][annotation] != result:
                            payload['metadata']['annotations'][annotation] = result
                            log.info(f'[MUTATE-ANNOTATION] ({operation_mode}) {container_name} Mutated ANNOTATION Value {annotation} to {result}')
                            if 'annotations' not in mutations:
                                mutations.append('annotations')
            if containers and 'containers' not in skip_modes:
                # containers are present
                RATIO_CPU = 5.0
                RATIO_MEM = 3.0
                for x in range(0, len(containers)):
                    container = containers[x]
                    container_name = container.get('name', 'default')
                    # ENV
                    # {.. 'command': ['sleep', 'infinity'], 'env': [{'name': 'my', 'value': 'password'}] ... }
                    if 'env' in container and 'env' not in skip_modes:
                        for env in range(0, len(container['env'])):
                            env_name = container['env'][env]['name']
                            env_value = container['env'][env]['value']
                            if 'nemu_' in env_value[0:5]:
                                env_hash = env_value[5:]
                                # here is where you set how to source the pass
                                # it can be a db, a vault, etc.. for this demo, i will use redis
                                env_pass = self.tpdb.get_pass(env_hash)
                                if env_pass:
                                    if 'env' not in mutations:
                                        mutations.append('env')
                                    log.info(f'[MUTATE-ENV] ({operation_mode}) {container_name} Mutated ENV {env_name} from {env_value} to *SECRET*')
                                    payload['spec']['containers'][x]['env'][env]['value'] = env_pass
                                else:
                                    log.info(f'[MUTATE-ENV] ({operation_mode}) {container_name} Mutated ENV {env_name} from {env_value} *NOT FOUND*')
                    # IMAGE (enforcement of version)
                    if 'image' in container and 'image' not in skip_modes:
                        image_version = container['image'].split(':')[-1]
                        image_name = container['image'].split(':')[0]
                        result = self.tpdb.get_image_version(f'nemu_image_{image_name}')
                        if result and 'image':
                            new_image = f'{image_name}:{result}'
                            old_image = f'{image_name}:{image_version}'
                            if new_image != old_image:
                                log.info(f'[MUTATE-IMAGE] ({operation_mode}) {container_name} Mutated IMAGE {image_name}:{image_version} to {new_image}')
                                payload['spec']['containers'][x]['image'] = new_image
                    # RESOURCES (LIMITS/REQUESTS)
                    # {... 'resources': {'limits': {'cpu': '2', 'memory': '1Gi'}, 'requests': {'cpu': '1', 'memory': '1Gi'}}, ... }
                    if 'resources' in container and 'resources' not in skip_modes:
                        requests = container['resources'].get('requests', {})
                        limits = container['resources'].get('limits', {})
                        old_resources = container['resources']
                        new_resources = {
                            'limits': {},
                            'requests': {}
                        }
                        cur_resources = {}
                        if limits.get('cpu', False):
                            cur_resources['limits_cpu'] = float(clean_cpu(limits['cpu'], mode='k8'))
                            new_resources['limits']['cpu'] = limits['cpu']
                        if limits.get('memory', False):
                            cur_resources['limits_mem'] = float(get_bytes(limits['memory']))
                            new_resources['limits']['memory'] = limits['memory']
                        if requests.get('cpu', False):
                            cur_resources['request_cpu'] = float(clean_cpu(requests['cpu'], mode='k8'))
                            new_resources['requests']['cpu'] = str(cur_resources['request_cpu'] / RATIO_CPU)
                        if requests.get('memory', False):
                            cur_resources['requests_mem'] = float(get_bytes(requests['memory']))
                            new_resources['requests']['memory'] = get_mb(cur_resources['requests_mem'] / RATIO_MEM)
                        # simulation
                        if 'prom_resources' not in skip_modes:
                            prometheus_metrics = {
                                'mem': query_prometheus('tuya-ws', mode='deployment', nature='mem'),
                                'cpu': query_prometheus('tuya-ws', mode='deployment', nature='cpu')
                            }
                            log.info(f"[RESOURCES] ({operation_mode}) {container_name} PromAvgCPU: {prometheus_metrics['cpu']} PromMaxMem: {prometheus_metrics['mem']}")
                            log.info(f"[LIMITS] ({operation_mode}) {container_name} CPU: {int(prometheus_metrics['cpu']['max'] * 1.33)}m max+33% & MEM: {int(prometheus_metrics['mem']['max'] * 1.33)}Mi max+33%")
                            log.info(f"[REQUESTS] ({operation_mode}) {container_name} CPU: {int(prometheus_metrics['cpu']['avg'] * 1.1)}m (avg+10%) & MEM: {int(prometheus_metrics['mem']['avg'] * 1.10)}Mi (avg+10%)")
                            #log.info(f"[DEVIATION] ({operation_mode}) {container_name} CPU Peak: {prometheus_metrics['cpu']['peak']}% vs CPU Off: {prometheus_metrics['cpu']['off']}%")
                            #log.info(f"[DEVIATION] ({operation_mode}) {container_name} MEM Peak: {prometheus_metrics['mem']['peak']}% vs MEM Off: {prometheus_metrics['mem']['off']}%")
                            if 'prom_resources' not in mutations:
                                mutations.append('prom_resources')
                                ## here we should replace the payload (if agreed with a formula)
                        log.info(f'[MUTATION-RESOURCES] ({operation_mode}) {container_name} Rationed From {old_resources} to {new_resources}')
                        if 'resources' not in mutations:
                            mutations.append('resources')
                        payload['spec']['containers'][x]['resources'] = new_resources
                        # should have rationed the L v R
        result = {}
        if org_payload != payload and 'patch' not in skip_modes:
            patch = jsonpatch.make_patch(json.loads(request.data)['request']['object'], payload)
            if patch and uid:
                rollback_patch = jsonpatch.make_patch(payload, json.loads(request.data)['request']['object'])
                action_log = {
                    'type': object_kind.lower(),
                    'operation': operation_mode,
                    'object': object_name,
                    'uid': uid,
                    'rollback_patch': f'ROLLBACK_{uid}.json',
                    'mutation_patch': f'PATCH_{uid}.json',
                    'time': time.time()
                }
                log.debug(f'[JSON-PATCH] ({operation_mode}) {uid} >> {patch}')
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
                log.info(f'[PATCH] ({operation_mode}) {uid} with {result}')
                with open(f'{self.patch_folder}/PATCH_{uid}.json', 'w') as patch_file:
                    patch_file.write(str(patch))
                with open(f'{self.patch_folder}/ROLLBACK_{uid}.json', 'w') as patch_file:
                    patch_file.write(str(rollback_patch))
                with open(self.mutation_log, 'a+') as mutation_log:
                    mutation_log.write(json.dumps(action_log))
                    mutation_log.write('\n')
                    log.debug(f'[MUTATION-LOG] ({operation_mode}) {uid} >> {object_kind} {object_name} Log and Patches Stored on {self.mutation_log}')
        #log.debug(f'[POST] to {path} >> H: {headers} >> D: {pprint(json.loads(request.data))}')
        return result, 200, {'Content-Type': 'application/json', 'Connection': 'close'}


def start_server(config):
    app = Flask(__name__)
    api = Api(app)
    api.add_resource(MutatorHook, '/mutate' )
    if not config.get('ssl', {}):
        return 'Please provide dict with crt and key'
    app.run(use_reloader=True, debug=True, port=config['web_port'], host='0.0.0.0', threaded=True, ssl_context=(config['ssl']['crt'], config['ssl']['key']))
    return True
