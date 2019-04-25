""" Geocode 1000 batches of addresses at a time. """

import os
import pandas as pd
import requests
import sqlalchemy as sqla
import sys
import tempfile
import subprocess
import threading
from queue import Queue
import time
import queue
import logging
import concurrent.futures


pd.options.display.max_columns = 999

import censusgeocode as cg


"""
Directions: 
Input_queue := pre-called address
output_queue = tuple(address, geocode)


worker:
    1. call address from the input_queue
    2. api call and get geocodes using the address in the input_queue
    3. input (address, geocode) into the output_queue
master:
    1. put addresses to the input_queue
    2. extract (address, geocode) from the output_queue and add it to the row of the pandas dataframe


Tasks needed to be programmed:
    1. Worker & functions
    2. Master & functions
    3. Master inputs the addresses to the input_queue
    4. Workers deployed in threads
    5. Master aggregates the information from various workers
     

parameters: n_thread, batchsize, timeout_specification

"""


def wrapper_api_call(df_input_addresses_queued):
    """
    API Wrapper (in this case censusgeocode pkg) call to return geo_codes.
    For censusgeocode pkg, input is a list of dict (input batch has to be less than 1000 addresses)
        and the output will be a list of [original address df, OrderedDict with geocodes].
    Dictionary has to have columns as street, city, state, and zip. (ID autogenerated in censusgeocode pkg).
    """
    logging.info("Worker is now working.")
    geo_codes_ordered_dict = cg.addressbatch(df_input_addresses_queued.to_dict('records'))
    logging.info("Worker's work is complete.")
    return geo_codes_ordered_dict


def work(current_queue, event):
    while not event.is_set() or not current_queue.empty():
        logging.info("Fetching a job from the queue...")
        df_input_addresses_queued = current_queue.get()
        logging.info("Ordering the worker to start the work...")
        return wrapper_api_call(df_input_addresses_queued)


class Master:
    """ Instantiating a Master class"""

    def __init__(self, df_input_addresses, n_threads, timeout_sec):
        """
        Master_input_df is the master dataframe with all the addresses that need to be geo-coded.
        """
        self.df_input_addresses = df_input_addresses
        self.df_input_addresses_queued = pd.DataFrame(columns=list(df_input_addresses))
        self.n_threads = n_threads
        self.timeout_sec = timeout_sec

    def load_up_queue(self, current_queue, event, df_input_addresses_queued):
        while not event.is_set():
            logging.info("Loading up the queue with an address data frame")
            current_queue.put(df_input_addresses_queued)

    def geo_codes_into_df(self, geo_codes_ordered_dict):
        logging.info("Changing result OrderedDict object to a pandas DataFrame")
        geo_codes_result_df = (pd.DataFrame.from_dict(geo_codes_ordered_dict))
        return geo_codes_result_df


def run_geocode_api(n_threads, input_df, timeout_sec, queue_size=50, queue_df_size=200):
    """
    Main function to run the geocoding using number of threads pre-defined.
    n_threads: number of threads that the task will run on
    input_df: dataframe that contains ALL the addresses (columns: street, city, state, zip)
    timeout_sec: seconds it will take to timeout the API call
    queue_size = the total queue size (not the dataframe length, but the number of dataframe that will be stored in
        the queue.Queue object.
    """
    event = threading.Event()
    q = queue.Queue(maxsize=queue_size)
    master = Master(input_df, n_threads, timeout_sec)
    geo_codes_orderd_dict = wrapper_api_call(df_input_addresses_queued=input_df.iloc[0:2, :])
    import pdb; pdb.set_trace()
    col_df = master.geo_codes_into_df(geo_codes_orderd_dict)
    master_output_df = pd.DataFrame(columns=list(col_df))
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as executor:
        for x in range(1, input_df.shape[0], queue_df_size):
            if x + queue_df_size <= input_df.shape[0]:
                df_address = input_df.iloc[x: x + queue_df_size, :]
                executor.submit(master.load_up_queue, q, event, df_address)
                geo_codes_ordered_dict = executor.submit(work, q, event)
            else:
                df_address = input_df.iloc[x: input_df.shape[0], :]
                executor.submit(master.load_up_queue, q, event, df_address)
                geo_codes_ordered_dict = executor.submit(work, q, event)
            geo_codes_result_df = master.geo_codes_into_df(geo_codes_ordered_dict)
            master_output_df = master_output_df.append(geo_codes_result_df,
                                                       sort=True,
                                                       ignore_index=True)
        return master_output_df