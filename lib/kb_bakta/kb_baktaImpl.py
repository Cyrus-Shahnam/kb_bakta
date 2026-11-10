# -*- coding: utf-8 -*-
#BEGIN_HEADER
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from installed_clients.KBaseReportClient import KBaseReport
from installed_clients.DataFileUtilClient import DataFileUtil
#END_HEADER


class kb_bakta:
    '''
    Module Name:
    kb_bakta

    Module Description:
    A KBase module: kb_bakta
    '''

    ######## WARNING FOR GEVENT USERS ####### noqa
    # Since asynchronous IO can lead to methods - even the same method -
    # interrupting each other, you must be *very* careful when using global
    # state. A method could easily clobber the state set by another while
    # the latter method is running.
    ######################################### noqa
    VERSION = "0.1.0"
    GIT_URL = "git@github.com:Fxe/kb_bakta.git"
    GIT_COMMIT_HASH = "0987738bd55827d0d9177962eea817b937d47e3e"

    #BEGIN_CLASS_HEADER

    # Reference data is built by scripts/prepare_data.sh at registration time and
    # mounted read-only at /data when the app runs.
    DATA_DIR = Path('/data')
    BAKTA_DB = DATA_DIR / 'db'

    @classmethod
    def check_bakta_db(cls):
        version_file = cls.BAKTA_DB / 'version.json'
        if not (cls.DATA_DIR / '__READY__').exists() or not version_file.exists():
            raise RuntimeError(
                f'Bakta reference data not found at {cls.BAKTA_DB}. The module must be '
                'registered with reference data (data-version in kbase.yml) so that KBase '
                'mounts it at /data; the app does not download the database at runtime.')
        with open(version_file) as fh:
            logging.info(f'Bakta DB: {json.load(fh)}')

    def run_bakta(self, proteins: dict) -> dict:
        """Run bakta_proteins on {feature_id: protein_sequence}; return the parsed JSON output."""
        self.check_bakta_db()

        work_dir = Path(tempfile.mkdtemp(prefix='bakta_', dir=self.shared_folder))
        input_faa = work_dir / 'input_genome.faa'
        output_dir = work_dir / 'output'  # must not exist yet, bakta creates it

        with open(input_faa, 'w') as fh:
            for i, s in proteins.items():
                fh.write(f'>{i}\n{s}\n')
        logging.info(f'{input_faa} created with {len(proteins)} proteins')

        cmd = [
            'bakta_proteins',
            '--db', str(self.BAKTA_DB),
            '--output', str(output_dir),
            '--prefix', 'input_genome',
            '--tmp-dir', str(work_dir),
            '--threads', str(self.threads),
            str(input_faa),
        ]
        logging.info('Running: ' + ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(result.stdout)
        print(result.stderr)
        if result.returncode != 0:
            raise RuntimeError(f'bakta_proteins failed (exit code {result.returncode}):\n'
                               f'{result.stderr[-4000:]}')

        with open(output_dir / 'input_genome.json') as fh:
            return json.load(fh)

    #END_CLASS_HEADER

    # config contains contents of config file in a hash or None if it couldn't
    # be found
    def __init__(self, config):
        #BEGIN_CONSTRUCTOR
        self.callback_url = os.environ['SDK_CALLBACK_URL']
        self.shared_folder = config['scratch']
        self.threads = os.cpu_count() or 4
        logging.basicConfig(format='%(created)s %(levelname)s: %(message)s',
                            level=logging.INFO)
        self.dfu = DataFileUtil(self.callback_url)
        #END_CONSTRUCTOR
        pass


    def run_kb_bakta(self, ctx, params):
        """
        This example function accepts any number of parameters and returns results in a KBaseReport
        :param params: instance of mapping from String to unspecified object
        :returns: instance of type "ReportResults" -> structure: parameter
           "report_name" of String, parameter "report_ref" of String
        """
        # ctx is the context object
        # return variables are: output
        #BEGIN run_kb_bakta

        print(params)

        dfu_get_result = self.dfu.get_objects({'object_refs': [f'{params["workspace_id"]}/{params["input_genome"]}']})
        genome_object = dfu_get_result['data'][0]['data']

        features = {}

        for f in genome_object['features']:
            protein_translation = f.get('protein_translation')
            feature_id = f['id']
            if protein_translation:
                if feature_id not in features:
                    features[feature_id] = protein_translation
                else:
                    raise ValueError('Duplicate feature id:', feature_id)

        annotation = self.run_bakta(features)
        print(annotation)

        report = KBaseReport(self.callback_url)
        report_info = report.create({'report': {'objects_created': [],
                                                'text_message': params['input_genome']},
                                                'workspace_name': params['workspace_name']})
        output = {
            'report_name': report_info['name'],
            'report_ref': report_info['ref'],
        }
        #END run_kb_bakta

        # At some point might do deeper type checking...
        if not isinstance(output, dict):
            raise ValueError('Method run_kb_bakta return value ' +
                             'output is not type dict as required.')
        # return the results
        return [output]

    def annotate_proteins(self, ctx, proteins):
        """
        :param proteins: instance of mapping from String to String
        :returns: instance of mapping from String to unspecified object
        """
        # ctx is the context object
        # return variables are: returnVal
        #BEGIN annotate_proteins

        returnVal = self.run_bakta(proteins)

        #END annotate_proteins

        # At some point might do deeper type checking...
        if not isinstance(returnVal, dict):
            raise ValueError('Method annotate_proteins return value ' +
                             'returnVal is not type dict as required.')
        # return the results
        return [returnVal]
    def status(self, ctx):
        #BEGIN_STATUS
        returnVal = {'state': "OK",
                     'message': "",
                     'version': self.VERSION,
                     'git_url': self.GIT_URL,
                     'git_commit_hash': self.GIT_COMMIT_HASH}
        #END_STATUS
        return [returnVal]
