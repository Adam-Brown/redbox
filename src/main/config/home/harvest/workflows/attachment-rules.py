from com.googlecode.fascinator.api.storage import StorageException
from com.googlecode.fascinator.common import FascinatorHome, JsonConfigHelper
from com.googlecode.fascinator.common.storage import StorageUtils
from java.io import ByteArrayInputStream, StringWriter
from java.lang import String
from org.apache.commons.io import IOUtils

import sys
import time
pathToWorkflows = FascinatorHome.getPath("harvest/workflows")
if sys.path.count(pathToWorkflows) == 0:
    sys.path.append(pathToWorkflows)
from json2 import read as jsonReader, write as jsonWriter


class IndexData:
    def __activate__(self, context):
        try:
            # Prepare variables
            self.index = context["fields"]
            self.object = context["object"]
            self.payload = context["payload"]
            self.params = context["params"]
            self.utils = context["pyUtils"]
            self.config = context["jsonConfig"]
            # Common data
            self.__newDoc()     # sets: self.oid, self.pid, self.itemType
            self.item_security = []
            self.owner = self.params.getProperty("owner", None)
            print " * Running attachment-rules.py... itemType='%s'" % self.itemType
            try:
                # Real metadata
                if self.itemType == "object":
                    self.__index("repository_name", self.params["repository.name"])
                    self.__index("repository_type", self.params["repository.type"])
                    self.__index("workflow_source", self.params["workflow.source"])
                    self.__metadata()
                # Make sure security comes after workflows
                self.__security()
            except Exception, e:
                print "  ERROR: '%s'" % str(e)
        except Exception, e:
            print " * Failed running attachment-rules.py - '%s'" % str(e)


    def __index(self, name, value):
        self.utils.add(self.index, name, value)

    def __indexList(self, name, values):
        for value in values:
            self.utils.add(self.index, name, value)


    def __newDoc(self):
        self.oid = self.object.getId()
        self.pid = self.payload.getId()
        metadataPid = self.params.getProperty("metaPid", "DC")
        #print "  pid='%s'" % (self.pid)

        self.utils.add(self.index, "storage_id", self.oid)
        if self.pid == metadataPid:
            self.itemType = "object"
        else:
            self.oid += "/" + self.pid
            self.itemType = "datastream"
            self.__index("identifier", self.pid)
        self.__index("id", self.oid)
        self.__index("item_type", self.itemType)
        ## always set to 'datastream' so that it does not show up in search results etc.
        #self.__index("item_type", "datastream")
        self.__index("last_modified", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        self.__index("harvest_config", self.params.getProperty("jsonConfigOid"))
        self.__index("harvest_rules",  self.params.getProperty("rulesOid"))
        self.__index("display_type", "attachment")


    def __metadata(self):
        wfMeta = self.__getJsonPayload("workflow.metadata")
        print " __metadata() wfMeta=%s" % str(wfMeta)
        pid = self.payload.getId()
        # Form processing
        formData = wfMeta.get("formData", {})
        for k, v in formData.iteritems():
            self.__index(k, v)
        self.__index("dc_title", "Attachment-"+formData.get("filename", ""))
        self.item_security.append("admin")
        self.__index("workflow_security", "admin")
        if formData.get("access_rights", "private")=="public":
            self.item_security.append("guest")
            self.__index("workflow_security", "guest")


    def __getJsonPayload(self, pid):
        try:
            payload = self.object.getPayload(pid)
            writer = StringWriter()
            IOUtils.copy(payload.open(), writer)
            dataDict = jsonReader(writer.toString())
            payload.close()
            return dataDict
        except:
            return {}

    def __saveJsonPayload(self, pid, dataDict):
        jsonString = String(jsonWriter(dataDict))
        inStream = ByteArrayInputStream(jsonString.getBytes("UTF-8"))
        try:
            StorageUtils.createOrUpdatePayload(self.object, pid, inStream)
        except StorageException:
            print " * ERROR updating '%s' payload!" % pid

    def __security(self):
        # Security
        roles = self.utils.getRolesWithAccess(self.oid)
        if roles is not None:
            # For every role currently with access
            for role in roles:
                # Should show up, but during debugging we got a few
                if role != "":
                    if role in self.item_security:
                        # They still have access
                        self.__index("security_filter", role)
                    else:
                        # Their access has been revoked
                        self.__revokeAccess(role)
            # Now for every role that the new step allows access
            for role in self.item_security:
                if role not in roles:
                    # Grant access if new
                    self.__grantAccess(role)
                    self.__index("security_filter", role)
        # No existing security
        else:
            if self.item_security is None:
                # Guest access if none provided so far
                self.__grantAccess("guest")
                self.__index("security_filter", role)
            else:
                # Otherwise use workflow security
                for role in self.item_security:
                    # Grant access if new
                    self.__grantAccess(role)
                    self.__index("security_filter", role)
        # Ownership
        if self.owner is None:
            self.__index("owner", "system")
        else:
            self.__index("owner", self.owner)


    def __grantAccess(self, newRole):
        schema = self.utils.getAccessSchema("derby");
        schema.setRecordId(self.oid)
        schema.set("role", newRole)
        self.utils.setAccessSchema(schema, "derby")


    def __revokeAccess(self, oldRole):
        schema = self.utils.getAccessSchema("derby");
        schema.setRecordId(self.oid)
        schema.set("role", oldRole)
        self.utils.removeAccessSchema(schema, "derby")


