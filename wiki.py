#TO DOs:
#1) Keep state of referrer in generic handler using refferer header rather than refURL query param I have everywhere.
#2) Make all of my classes use the generic cache+db write and read functions (Wiki, Edit do this already, but signup/login do not)
#3) Learn about parents/ancestors in db stuff. Seems important, but sort of brushed over it.
#4) Modify db/cache write handler function so that it can do a conditional check before writing as part of a transaction.



import webapp2
import sys 
import os
import cgi
import re
import cookies
import json
import datetime
import logging
from google.appengine.api import memcache
from random import randint
from google.appengine.api import users
from google.appengine.ext import ndb
from google.appengine.ext import db
#from google.appengine.ext.db import metadata
import jinja2
import saltyPassword

template_dir = os.path.join(os.path.dirname(__file__), "templates")
jinja_env = jinja2.Environment(loader = jinja2.FileSystemLoader(template_dir), autoescape = False) 
#autoescape set to False since this is a wiki. does NOT do anything to help server side escaping.

#generic handler class for anytime you want to write a web page. can be used for both get and post.
#have all of your page-specific classes inherit from here, call render with a template name and list of **kwargs to fill in the template values.
class Handler(webapp2.RequestHandler):

    def write(self, *a, **kw):
        self.response.out.write(*a, **kw)
        
    def render_str(self, template, **params):
        t = jinja_env.get_template(template)
        return t.render(params)
        
    def render(self, template, **kw):
        self.write(self.render_str(template, **kw))

    def login_check(self):
        if not cookies.get_cookie_string(self.request,"username","")[1]:
            self.logState = "login"
            self.logURL = "/login?refURL=%s" % self.request.path[1:]
            return False
        else:
            self.logState = "logout"
            self.logURL = "/logout?refURL=%s" % self.request.path[1:]
            self.username = cookies.get_usable_cookie_value(self.request, "username", "")
            return self.username

    def startup(self, requestObj):
        self.page_id = self.set_page_id(requestObj)
        logging.info("self.page_id is %s" % self.page_id)
        self.set_history_URL()
        self.login_check()

    def set_page_id(self, requestObj):
        logging.info("path is %s" % requestObj.path)
        page_id = requestObj.path
        if "/_edit" in page_id:
            page_id = page_id[6:]
        if "/_history" in page_id:
            page_id = page_id[9:]
        return page_id

    def log_user_in(self,userObj):
            real_username = userObj.username
            readableUsernameCookie = cookies.get_usable_cookie_value(self.request,real_username,"")
            readableUsernameCookie = real_username
            cookies.set_secure_cookie(self.response, "username", readableUsernameCookie, "/")

    def log_user_out(self):
        cookies.delete_cookie(self.request, self.response, "username","/")

    def get(self):
        self.response.out.write("no GET method defined!")

    def cache_and_db_write(self, cacheKey, dbRecord): 
        #query is the query to run to update the cachekey
        logging.info("writing to the database")
        foo = dbRecord.put()
        logging.info("reading from the database")
        cacheObj = dbRecord
        logging.info("setting memcache with %s, %s" % (cacheKey, cacheObj))
        memcache.set(cacheKey, cacheObj) 

    def set_history_URL(self):
        self.historyURL = "/_history%s" % self.page_id

    def read_from_cache_or_db(self, cacheKey, dbQuery, firstOrAll): 
    #firstOrAll string specifies whether you want first result from a DB query, or the full list of results.
    #Should be "first" or "all".

        logging.info('reading %s from memcache' % cacheKey)
        val = memcache.get(cacheKey)
        if val:
            logging.info('%s was found in memcache with value %s' % (cacheKey, val))
            return val

        else:
            logging.info('%s was NOT found in memcache. Checking DB.' % cacheKey)
            data = db.GqlQuery(dbQuery)
            if data.count() < 1:
                logging.info('Not in the db.')
                return False
            else:
                logging.info('%s is result from DB.' % data)
                if getOrFetch == "first":
                    memcache.set(cacheKey,data.get())
                    return data.get()
                elif getOrFetch == "all":
                    memcache.set(cacheKey,data.fetch())
                    return data.fetch()

    def get_query_param(self, getRequestObj, key, defaultStr):
        if key in getRequestObj.params:
            val = getRequestObj.params[key]
        else:
            val = defaultStr
        return val

class Entry (db.Model):
    markup = db.TextProperty(required = True)
    created = db.DateTimeProperty(auto_now_add = True)
    url = db.StringProperty(required = True)
    createdBy = db.StringProperty(required = True)

class UserDB(db.Model):
    #username is the unique key. When creating a new user, specify 'key_name = username'
    #e.g. foo = Entry (username=usernameStr, pw = pwStr, key_name = usernameStr)
    username = db.StringProperty(required = True)
    password = db.StringProperty(required = True)
    email = db.StringProperty(required = False)

class WikiPage(Handler):
    def get(self, dont_use_me):
        self.startup(self.request)
        markup = self.read_from_cache_or_db(self.page_id, "Select * from Entry where url = '%s'" % self.page_id, "first")
        if markup:
            self.render("main.html", logState = self.logState, logURL = self.logURL, \
                    editState = "edit", editURL = "/_edit%s" % self.page_id, \
                    historyURL = self.historyURL, markup = markup.markup)
        else:
            self.redirect("/_edit%s" % self.page_id)
        

class EditPage(Handler):
    def get(self, dont_use_me):
        self.startup(self.request)
        if self.logState != 'logout':
            self.redirect('/login/?refURL=/_edit%s' % self.page_id)
        markupText = self.read_from_cache_or_db(self.page_id, "Select * from Entry where url = '%s'" % self.page_id, "first")
        if markupText:
            self.render("edit.html", logState = self.logState, logURL = self.logURL, \
                        editState = "view", editURL = "%s" % self.page_id, historyURL = self.historyURL, \
                        markup = markupText.markup)
        else:
            self.render("edit.html", logState = self.logState, logURL = self.logURL, editState = "view", \
                historyURL = self.historyURL, editURL = "%s" % self.page_id)
        

    def post(self, dont_use_me):
        self.startup(self.request)
        markup = self.request.get('markup')
        if not markup:
            self.render("edit.html", logState = self.logState, logURL = self.logURL, \
                         editState = "view", editURL = "%s" % self.page_id, historyURL = self.historyURL, \
                         error = "No blank submissions plz!")
        else:
            dbObj = Entry(markup = markup, url = self.page_id, createdBy = self.username)
            self.cache_and_db_write(self.page_id, dbObj)
            self.redirect("%s" % self.page_id)

class HistoryPage(Handler):

    def get(self, dont_use_me):
        query = "Select * from Entry order by createdBy desc"
        historyList = self.read_from_cache_or_db("history_%s" % self.page_id, query, "all") #this is going to break
        #To Do:
        #1) Create history template.
        #2) Put HistoryPage in URL mapping
        #3) Make sure history gets cached appropriately. 

class Signup(Handler):

    #to dos: finish post function so that it...
    #   - Do database write in a transaction, rather than checking for username existance in one call, and then writing in a second call
    #        This is bad because state of DB could theoretically change between time of those calls.
    #   - validates that the html inputs are correct (email syntax)
    #   - In a perfect world, we'd wait for a response back from the db saying that the write was successful before setting the cookie.

    def render_main(self, email="s", username="s", password="s",verify="s", error=""):
        kwargs = {"email":email, "username":username, "password":password, "verify":verify, "error":error}
        self.render("signup.html",**kwargs)

    def get(self):
        self.render_main()

    def post(self):
        email = self.request.get("email")
        username = self.request.get("username")
        password = self.request.get("password")
        verify = self.request.get("verify")

        refURL = str(self.get_query_param(self.request, 'refURL', '/'))

        #need all of the escaping here bc auto-escape is set to false globally bc this is a wiki :).
        if password != verify:
            self.render_main(cgi.escape(email),cgi.escape(username),cgi.escape(password),cgi.escape(verify),"Make sure your passwords match!")
        elif not password or not verify or not username:
            self.render_main(cgi.escape(email),cgi.escape(username),cgi.escape(password),cgi.escape(verify),"Please fill in every field.")
        elif UserDB.get_by_key_name(username):
            self.render_main(cgi.escape(email),cgi.escape(username),cgi.escape(password),cgi.escape(verify),"That username exists.")
        else:
            password = saltyPassword.generate_salted_password(password)
            newUser = UserDB(email = email, username = username, password = password, key_name = username)
            newUser.put()
            self.log_user_in(newUser)
            self.redirect(refURL)

class Login(Handler):

    def render_main(self,username="s", password="s", error=""):
        kwargs = {"username":username,"password":password, "error":error}
        self.render("login.html", **kwargs)

    def get(self):
        self.render_main()

    def post(self):     
        username = self.request.get("username")
        password = self.request.get("password")

        if not username or not password:
            error = "invalid username/password combination - 0"
            self.render_main(username,password,error)
            return

        user_entity = UserDB.get_by_key_name(username)
        if user_entity and saltyPassword.is_valid_password(password,user_entity):
            self.log_user_in(user_entity)
            refURL = str(self.get_query_param(self.request, 'refURL', '/'))
            logging.info('refURL IS %s' % refURL)
            self.redirect(refURL)   

        else:
            error = "invalid username/password combination - 1"
            self.render_main(username,password,error)

class Logout(Handler):

    def get(self):
        refURL = str(self.get_query_param(self.request, 'refURL', '/'))
        self.log_user_out()
        self.redirect(refURL)

class Flush(Handler):

    def get(self):
        self.startup()
        memcache.flush_all()
        self.redirect("/")


PAGE_RE = r'(?:/([a-zA-Z0-9_-]+/?)*)'
application = webapp2.WSGIApplication([ (r"/signup/?", Signup), \
                                       (r"/login/?",Login), (r"/logout/?",Logout), \
                                       (r"/flush/?", Flush), ('/_edit' + PAGE_RE, EditPage), (PAGE_RE, WikiPage)  \
                                       ], debug=True) 
                                       
def handle_404(request, response, exception):
    response.write("can't find that url")
    response.set_status(404)

def handle_500(request, response, exception):
    response.write("500")
    response.set_status(500)

#application.error_handlers[404] = handle_404
#application.error_handlers[500] = handle_500



