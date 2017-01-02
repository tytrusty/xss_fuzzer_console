#!/usr/bin/env python

# import modules
from urlparse import urlparse, parse_qs, ParseResult
from urllib import urlencode
import os, binascii
import threading
import collections
import connect 
import time
import util
import sys
import re

# Class containing necessary metadata for each attack vector
class AttackContext:
    # Context essentially refers to the attack location 
    cookie = ''        # Inserted cookie to find
    data = ''          # Raw HTML
    tag = ''           # Direct Parent Tag
    tag_closed = False # Has the open parent tag been closed
    is_js = False      # In a javascript context
    in_value = True    # Has iteration passed the assignment
    delimiter = ''     # Is the input encapsulated by ' or "

    # Initialize class variables and parse current context
    def __init__(self, data, cookie, pos):
        self.data = data
        self.cookie = cookie
        d = 0
        for i in reversed(data[0:pos]):
            d += 1
            
            if i == '>': # Parent tag is closed
                self.tag_closed = True
            
            elif i == '<': # Look complete, because tag found
                self.set_tag(pos-d+1, pos)
                break
            
            elif i == '{': # JavaScript context
                self.is_js = True

            elif i == '=': # Value assignment complete
                self.in_value = False

            # Checking value delimiter
            elif i == '\'' or i == '\"' and self.in_value:
                self.delimiter = i

    # Set the Parent tag for the current context
    def set_tag(self, start, end):
        # Split using space as delimiter
        no_space = self.data[start:end].split(' ')
        tag = no_space[0]
        
        # If tag is closed, make sure closing tag isn't included
        if self.tag_closed:
            tag = tag.split('>')[0]

        self.tag = tag # Tag set

# Class containing Attack URLs with their associated metadata
class AttackURL:
    cookie = str(binascii.b2a_hex(os.urandom(3))) # Generate cookie
    url = ''
    data = '' # html data
    atk_vectors = list() # attack vectors -- list of AttackContext's

    def __init__(self, url):
        self.url = url

    def init_context(self):
        if self.data == '':
            return
        else:
            pass # Retrieve data

        # Find all cookie reflections in the HTML
        match = util.string_match(self.data, self.cookie)
        for pos in match:
            context = AttackContext(self.data, self.cookie, pos)

    # Generates an attack object for parameterized URLs
    @staticmethod
    def create(parsed_url, params):
        p = parsed_url
        # Changing each argument value to the cookie
        for param, value in params.items(): 
            params[param] = AttackURL.cookie
        new_params = urlencode(params, doseq=True)
        new_url = ParseResult(p.scheme, p.netloc, p.path, p.params,
                new_params, p.fragment).geturl()

        return AttackURL(new_url) # Return new attack object

# Synchronized Ordered Dictionary that serves as a queue
class DictQueue:
    spider_continue = True
    delay = 0 
    queue_size = 0
    cv = threading.Condition()
    timer_lock = threading.Lock()
    dict_queue = dict()     # Links not yet visited
    visited_links = dict()  # Dictionary of visiteed links
    param_links = dict()    # Dict for parameterized URLs
                            

    # Adding initial target link
    def __init__(self, link):
        self.add_links(link)

    def get_link(self):
        # set timeout
        self.cv.acquire()
        while not len(self.dict_queue):
            self.cv.wait()
        self.queue_size -= 1
       
        item = self.dict_queue.popitem()             # pop from queue
        self.visited_links.update({item[0]:item[1]}) # add to visited dir
        self.cv.release()

        return item

    # Links added en-masse to avoid constant synch procedure calls
    def add_links(self, links): # links represented as a dictionary
        self.cv.acquire()
        # upload links
        for url, depth in links.items():
            # Reference visited links
            if depth == -1: # If recursive limit is reached
                continue

            # Checking if link has parameters
            parse = urlparse(url)
            params = parse_qs(parse.query.encode('utf-8')) 
            if params: # If params, create attack object
                # Create Attack Object
                attack_obj = AttackURL.create(parse, params) 
                url = attack_obj.url # Retreive attack url
                self.param_links.update({url: attack_obj})
            
            # Avoid repeats if at same or lower depth 
            q_depth = self.dict_queue.get(url, -1)
            v_depth = self.visited_links.get(url, -1)
            if depth <= q_depth or depth <= v_depth:
                continue
            
            # Adding to unvisited links queue
            self.dict_queue.update({url: depth})
        
        self.cv.notify(1)
        self.cv.release()

    # Provides thread-safe delayed connection, if necessary
    def delay_conn(self, link):
        if self.delay != 0: # Only one request per delay interval 
            self.timer_lock.acquire()
            time.sleep(self.delay)
            self.timer_lock.release()
        
        # Time of connection is not included in the delay
        return connect.scrape_links(link[0], link[1])

# Function executed by spider threads
def spider_thread(queue):
    while queue.spider_continue:
        # Retrieve URL and make connection
        link = queue.get_link()
        response = queue.delay_conn(link)

        if response == None: continue
        link_dict = response[0]
        data = response[1]
       
        # Storing data in attack object if visited parameterized url
        param_obj = queue.param_links.get(link[0]) 
        if param_obj != None:   
            param_obj.data = data
            param_obj.init_context()
        # Adding discovered links to queue
        queue.add_links(link_dict)




