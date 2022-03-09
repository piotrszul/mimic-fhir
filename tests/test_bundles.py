""".
Test script for different bundles in MIMIC-FHIR
Main tests are:
- Data bundle: Organization and Medication
- Patient bundle: Patient/Encounter/Condition/Procedure
- Meds bundle: MedicationRequest/MedicationDispense/MedicationAdministration
- Micro bundle: ObservationMicroTest/ObservationMicroOrg/ObservationMicroSusc
- Lab bundle: ObservationLabs
- ICU base bundle: EncounterICU/MedicationAdministrationICU
- ICU observation bundle: ObservationChartevents/ObservationOutputevents/ObservationDatetimeevents

"""

import json
import requests
import logging
import os
import subprocess
import pytest
import numpy as np
import pandas as pd

#from fhir.resources.bundle import Bundle
from py_mimic_fhir.bundle import Bundle, Bundler

FHIR_SERVER = os.getenv('FHIR_SERVER')


# Function to find links between a patient and certain resources.
# Allows for more complete testing if sending full bundle
def get_pat_id_with_links(db_conn, resource_list):
    q_resource = 'SELECT pat.fhir FROM mimic_fhir.patient pat'

    # Dynamically create query to find links between a patient and certain resources
    for idx, resource in enumerate(resource_list):
        q_resource = f"""{q_resource} 
            INNER JOIN mimic_fhir.{resource} t{idx}
                ON pat.id = t{idx}.patient_id 
        """
    q_resource = f'{q_resource} LIMIT 20;'

    resource = pd.read_sql_query(q_resource, db_conn)
    return resource.fhir[0]['id']


# Get n patient_ids
def get_n_patient_id(db_conn, n_patient):
    q_resource = f"SELECT * FROM mimic_fhir.patient LIMIT {n_patient}"
    resource = pd.read_sql_query(q_resource, db_conn)
    patient_ids = [fhir['id'] for fhir in resource.fhir]

    return patient_ids


def test_bundle_patient_all_resources(db_conn):
    # Get n patient ids to then bundle and post
    patient_ids = get_n_patient_id(db_conn, 1)

    # Create bundle and post it
    bundler = Bundler(patient_id)
    bundler.generate_all_bundles()
    response_list = bundler.post_all_bundles(FHIR_SERVER)

    result = True
    for response in response_list:
        if response['resourceType'] == 'OperationOutcome':
            result = False
            logging.error(response)
    assert result


def test_bundle_multiple_patient_all_resources(db_conn):
    # Get n patient ids to then bundle and post
    patient_ids = get_n_patient_id(db_conn, 50)

    # Create bundle and post it
    result = True
    for patient_id in patient_ids:
        bundler = Bundler(patient_id)
        bundler.generate_all_bundles()
        response_list = bundler.post_all_bundles(FHIR_SERVER)

        for response in response_list:
            if response['resourceType'] == 'OperationOutcome':
                result = False
                logging.error(response)
    assert result


def test_bad_bundle():
    bundle = Bundle()
    bad_resource = [{'resourceType': 'BAD RESOURCE', 'id': '123'}]
    bundle.add_entry(bad_resource)
    bundle.request(FHIR_SERVER)
    assert bundle.response['resourceType'] == 'OperationOutcome'


def test_bad_code_in_bundle():
    pat_resource = {
        'resourceType': 'Patient',
        'id': '123456',
        'gender': 'FAKE CODE'
    }
    bundle = Bundle()
    bad_resource = [pat_resource]
    bundle.add_entry(bad_resource)
    bundle.request(FHIR_SERVER)
    assert bundle.response['resourceType'] == 'OperationOutcome'


def test_patient_bundle(db_conn):
    # Get patient_id that has resources from the resource_list
    resource_list = ['encounter', 'condition', 'procedure']
    patient_id = get_pat_id_with_links(db_conn, resource_list)

    # Create bundle and post it
    bundler = Bundler(patient_id)
    bundler.generate_patient_bundle()
    response = bundler.patient_bundle.request(FHIR_SERVER)
    assert response['resourceType'] == 'Bundle'


def test_microbio_bundle(db_conn):
    # Get patient_id that has resources from the resource_list
    resource_list = [
        'observation_micro_test', 'observation_micro_org',
        'observation_micro_susc'
    ]
    patient_id = get_pat_id_with_links(db_conn, resource_list)

    # Create bundle
    bundler = Bundler(patient_id)

    # Generate and post patient bundle, must do first to avoid referencing issues
    bundler.generate_patient_bundle()
    bundler.patient_bundle.request(FHIR_SERVER)

    #  Generate and post micro bundle
    bundler.generate_micro_bundle()
    response = bundler.micro_bundle.request(FHIR_SERVER)
    logging.error(patient_id)
    assert response['resourceType'] == 'Bundle'


def test_lab_bundle(db_conn):
    # Get patient_id that has resources from the resource_list
    resource_list = ['observation_labs']
    patient_id = get_pat_id_with_links(db_conn, resource_list)

    # Create bundle
    bundler = Bundler(patient_id)

    # Generate and post patient bundle, must do first to avoid referencing issues
    bundler.generate_patient_bundle()
    bundler.patient_bundle.request(FHIR_SERVER)

    #  Generate and post lab bundle
    bundler.generate_lab_bundle()
    response = bundler.lab_bundle.request(FHIR_SERVER)
    logging.error(patient_id)
    assert response['resourceType'] == 'Bundle'


def test_med_pat_bundle(db_conn):
    # Get patient_id that has resources from the resource_list
    resource_list = [
        'medication_request', 'medication_administration'
    ]  # Add medication_dispense after updating IG
    patient_id = get_pat_id_with_links(db_conn, resource_list)

    # Create bundle
    bundler = Bundler(patient_id)

    # Generate and post patient bundle, must do first to avoid referencing issues
    bundler.generate_patient_bundle()
    bundler.patient_bundle.request(FHIR_SERVER)

    #  Generate and post micro bundle
    bundler.generate_med_bundle()
    response = bundler.med_bundle.request(FHIR_SERVER)
    logging.error(patient_id)
    assert response['resourceType'] == 'Bundle'


# Only passing a small portion of the meds here (~100)
def test_iterative_med_data_bundle(med_data_bundle_resources):
    response_list = []
    split_count = len(med_data_bundle_resources) // 500 + 1
    resource_splits = np.array_split(med_data_bundle_resources, split_count)
    for resource_list in resource_splits:
        bundle = Bundle()
        bundle.add_entry(resource_list)
        response = bundle.request(FHIR_SERVER)
        response_list.append(response['resourceType'])
        logging.error(response)
    assert 'OperationOutcome' not in response_list


# Need to figure out how to get medication references working if only a subuset of the Medication resources have been posted
# OR just post all medication resources..
def test_med_data_bundle(db_conn):
    bundle = Bundle()
    bundle.add_entry(med_pat_bundle_resources)
    bundle.request(FHIR_SERVER)
    assert bundle.response['resourceType'] == 'Bundle'


# Test icu base bundle that include EncounterICU and MedicationAdminstrationICU
def test_icu_base_bundle(db_conn):
    # Get patient_id that has resources from the resource_list
    resource_list = [
        'encounter_icu', 'procedure_icu', 'medication_administration_icu'
    ]
    patient_id = get_pat_id_with_links(db_conn, resource_list)

    # Create bundle
    bundler = Bundler(patient_id)

    # Generate and post patient bundle, must do first to avoid referencing issues
    bundler.generate_patient_bundle()
    bundler.patient_bundle.request(FHIR_SERVER)

    #  Generate and post icu base bundle
    bundler.generate_icu_base_bundle()
    response = bundler.icu_base_bundle.request(FHIR_SERVER)
    logging.error(patient_id)
    assert response['resourceType'] == 'Bundle'


# Test all observation resources coming out of the ICU
def test_icu_observation_bundle(db_conn):
    # Get patient_id that has resources from the resource_list
    resource_list = [
        'observation_chartevents', 'observation_datetimeevents',
        'observation_outputevents'
    ]
    patient_id = get_pat_id_with_links(db_conn, resource_list)

    # Create bundle
    bundler = Bundler(patient_id)

    # Generate and post patient bundle, must do first to avoid referencing issues
    bundler.generate_patient_bundle()
    bundler.patient_bundle.request(FHIR_SERVER)

    #  Generate and post icu observation bundle
    bundler.generate_icu_obs_bundle()
    response = bundler.icu_obs_bundle.request(FHIR_SERVER)
    logging.error(patient_id)
    assert response['resourceType'] == 'Bundle'
