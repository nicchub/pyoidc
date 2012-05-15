from oic.oic.message import AuthnToken, CheckSessionRequest, CheckIDRequest, EndSessionRequest, AuthorizationResponse, RegistrationResponse, IdToken, OpenIDSchema, ProviderConfigurationResponse, IssuerRequest
from oic.oic.message import AuthorizationRequest
from oic.oic.message import OpenIDRequest
from oic.oic.message import Claims
from oic.oic.message import AccessTokenResponse
from oic.oic.message import IDTokenClaim
from oic.oic.message import UserInfoClaim
from oic.oic.message import RefreshSessionRequest
from oic.oic.message import RegistrationRequest
from oic.oic.message import UserInfoRequest
from oic.oic.message import AccessTokenRequest
from oic.oic.message import RefreshAccessTokenRequest

from oic.oic.exception import AccessDenied

__author__ = 'rohe0002'

import urlparse
import json

from oic import oauth2

from oic.oauth2 import AUTHN_METHOD as OAUTH2_AUTHN_METHOD
from oic.oauth2 import DEF_SIGN_ALG
from oic.oauth2 import HTTP_ARGS
from oic.oauth2 import rndstr

from oic.utils import time_util
from oic.utils import jwt

#from oic.utils.time_util import time_sans_frac
from oic.utils.time_util import utc_now
from oic.utils.time_util import epoch_in_a_while

ENDPOINTS = ["authorization_endpoint", "token_endpoint",
             "userinfo_endpoint", "refresh_session_endpoint",
             "check_session_endpoint", "end_session_endpoint",
             "registration_endpoint", "check_id_endpoint"]

RESPONSE2ERROR = {
    "AuthorizationResponse": ["AuthorizationErrorResponse",
                              "TokenErrorResponse"],
    "AccessTokenResponse": ["TokenErrorResponse"],
    "IdToken": ["ErrorResponse"],
    "RegistrationResponse": ["ClientRegistrationErrorResponse"],
    "OpenIDSchema": ["UserInfoErrorResponse"]
}

REQUEST2ENDPOINT = {
    "AuthorizationRequest": "authorization_endpoint",
    "OpenIDRequest": "authorization_endpoint",
    "AccessTokenRequest": "token_endpoint",
    "RefreshAccessTokenRequest": "token_endpoint",
    "UserInfoRequest": "userinfo_endpoint",
    "CheckSessionRequest": "check_session_endpoint",
    "CheckIDRequest": "check_id_endpoint",
    "EndSessionRequest": "end_session_endpoint",
    "RefreshSessionRequest": "refresh_session_endpoint",
    "RegistrationRequest": "registration_endpoint"
}

# -----------------------------------------------------------------------------
MAX_AUTHENTICATION_AGE = 86400
JWT_BEARER = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
OIDCONF_PATTERN = "%s/.well-known/openid-configuration"

AUTHN_METHOD = OAUTH2_AUTHN_METHOD.copy()

def assertion_jwt(cli, keys, audience, algorithm=DEF_SIGN_ALG):
    at = AuthnToken(iss = cli.client_id, prn = cli.client_id, aud = audience,
                    jti = rndstr(8), exp = int(epoch_in_a_while(minutes=10)),
                    iat = utc_now())
    return at.to_jwt(key=keys, algorithm=algorithm)

#noinspection PyUnusedLocal
def client_secret_jwt(cli, cis, authn_method, request_args=None,
                      http_args=None, req=None):

    # signing key is the client secret
    signing_key = cli.keystore.get_sign_key()

    # audience is the OP endpoint
    audience = cli._endpoint(REQUEST2ENDPOINT[cis.type()])

    cis["client_assertion"] = assertion_jwt(cli, signing_key, audience,
                                            "RS256")
    cis["client_assertion_type"] = JWT_BEARER

    try:
        del cis["client_secret"]
    except KeyError:
        pass

    return {}

#noinspection PyUnusedLocal
def private_key_jwt(cli, cis, authn_method, request_args=None,
                    http_args=None, req=None):

    # signing key is the clients rsa key for instance
    signing_key = cli.keystore.get_sign_key()

    # audience is the OP endpoint
    audience = cli._endpoint(REQUEST2ENDPOINT[cis.type()])

    cis["client_assertion"] = assertion_jwt(cli, signing_key, audience,
                                            algorithm="RS512")
    cis["client_assertion_type"] = JWT_BEARER

    try:
        del cis["client_secret"]
    except KeyError:
        pass

    return {}

AUTHN_METHOD.update({"client_secret_jwt": client_secret_jwt,
                     "private_key_jwt": private_key_jwt})

# -----------------------------------------------------------------------------
ACR_LISTS = [
    ["0", "1", "2", "3", "4"],
]

def verify_acr_level(req, level):
    if req is None:
        return level
    elif req == {"optional": True}:
        return level
    else:
        for _r in req["values"]:
            for alist in ACR_LISTS:
                try:
                    if alist.index(_r) <= alist.index(level):
                        return level
                except ValueError:
                    pass

    raise AccessDenied

#def verify_id_token(self, **kwargs):
#    if self.id_token:
#        # Try to decode the JWT, checks the signature
#        idt = message("IdToken").from_jwt(str(self.id_token), kwargs["key"])
#        if not idt.verify(**kwargs):
#            return False
#
#        if "at_hash" in idt:
#            assert idt["at_hash"] == jwt.left_hash(kwargs["access_token"])
#
#        if "c_hash" in idt:
#            assert idt["c_hash"] == jwt.left_hash(kwargs["code"])
#
#    return super(self.__class__, self).verify(**kwargs)
#
#MESSAGE["AuthorizationResponse"]["verify"] = verify_id_token()

# -----------------------------------------------------------------------------

class Token(oauth2.Token):
    _response = AccessTokenResponse


class Grant(oauth2.Grant):
    _authz_resp = "AuthorizationResponse"
    _acc_resp = "AccessTokenResponse"
    _token_class = Token

    def add_token(self, resp):
        tok = self._token_class(resp)
        if tok.access_token:
            self.tokens.append(tok)
        else:
            _tmp = getattr(tok, "id_token", None)
            if _tmp:
                self.tokens.append(tok)

#noinspection PyMethodOverriding
class Client(oauth2.Client):
    _endpoints = ENDPOINTS

    def __init__(self, client_id=None, ca_certs=None, grant_expire_in=600,
                 jwt_keys=None, client_timeout=0):

        oauth2.Client.__init__(self, client_id, ca_certs, grant_expire_in,
                               client_timeout=client_timeout,
                               jwt_keys=jwt_keys)

        self.file_store = "./file/"
        self.file_uri = "http://localhost/"

        # OpenID connect specific endpoints
        for endpoint in ENDPOINTS:
            setattr(self, endpoint, "")

        self.id_token=None
        self.log = None

        self.request2endpoint = REQUEST2ENDPOINT
        self.response2error = RESPONSE2ERROR
        self.grant_class = Grant
        self.token_class = Token
        self.authn_method = AUTHN_METHOD

    def _get_id_token(self, **kwargs):
        try:
            return kwargs["id_token"]
        except KeyError:
            grant = self.get_grant(**kwargs)

        if grant:
            try:
                _scope = kwargs["scope"]
            except KeyError:
                _scope = None

            for token in grant.tokens:
                if token.scope and _scope:
                    flag = True
                    for item in _scope:
                        try:
                            assert item in token.scope
                        except AssertionError:
                            flag = False
                            break
                    if not flag:
                        break
                if token.id_token:
                    return token.id_token

        return None

    #noinspection PyUnusedLocal
    def make_openid_request(self, arq, keys, userinfo_claims=None,
                            idtoken_claims=None, algorithm=DEF_SIGN_ALG,
                            **kwargs):
        """
        Construct the specification of what I want returned.
        The request will be signed
        """

        oir_args = {}

        if userinfo_claims is not None:
            # UserInfoClaims
            claim = Claims(**userinfo_claims["claims"])

            uic_args = {}
            for prop, val in userinfo_claims.items():
                if prop == "claims":
                    continue
                if prop in UserInfoClaim.c_param.keys():
                    uic_args[prop] = val

            uic = UserInfoClaim(claims=claim, **uic_args)
        else:
            uic = None

        if uic:
            oir_args["userinfo"] = uic

        if idtoken_claims is not None:
            #IdTokenClaims
            try:
                _max_age = idtoken_claims["max_age"]
            except KeyError:
                _max_age=MAX_AUTHENTICATION_AGE

            id_token = IDTokenClaim(max_age=_max_age)
            if "claims" in idtoken_claims:
                idtclaims = Claims(**idtoken_claims["claims"])
                id_token["claims"] = idtclaims
        else: # uic must be != None
            id_token = IDTokenClaim(max_age=MAX_AUTHENTICATION_AGE)

        if id_token:
            oir_args["id_token"] = id_token

        for prop, val in arq.items():
            oir_args[prop] = val

        for attr in ["scope", "prompt", "response_type"]:
            if attr in oir_args:
                oir_args[attr] = " ".join(oir_args[attr])

        oir = OpenIDRequest(**oir_args)

        return oir.to_jwt(key=keys, algorithm=algorithm)

    def construct_AuthorizationRequest(self,
                                       request=AuthorizationRequest,
                                       request_args=None, extra_args=None,
                                       **kwargs):

        if request_args is not None:
            if "nonce" not in request_args:
                request_args["nonce"] = rndstr(12)
        else:
            request_args = {"nonce": rndstr(12)}

        return oauth2.Client.construct_AuthorizationRequest(self, request,
                                                            request_args,
                                                            extra_args,
                                                            **kwargs)

    def construct_OpenIDRequest(self, request=OpenIDRequest,
                                request_args=None, extra_args=None, **kwargs):

        if request_args is not None:
            for arg in ["idtoken_claims", "userinfo_claims"]:
                if arg in request_args:
                    kwargs[arg] = request_args[arg]
                    del request_args[arg]
            if "nonce" not in request_args:
                request_args["nonce"] = rndstr(12)
        else:
            request_args = {"nonce": rndstr(12)}

        areq = oauth2.Client.construct_AuthorizationRequest(self, request,
                                                            request_args,
                                                            extra_args,
                                                            **kwargs)

        if "key" not in kwargs:
            kwargs["keys"] = self.keystore.get_sign_key()

        if "userinfo_claims" in kwargs or "idtoken_claims" in kwargs:
            areq["request"] = self.make_openid_request(areq, **kwargs)

        return areq

    def construct_AccessTokenRequest(self, request=AccessTokenRequest,
    #noinspection PyUnusedLocal
                                     request_args=None, extra_args=None,
                                     **kwargs):

        return oauth2.Client.construct_AccessTokenRequest(self, request,
                                                          request_args,
                                                          extra_args, **kwargs)

    def construct_RefreshAccessTokenRequest(self,
                                            request=RefreshAccessTokenRequest,
                                            request_args=None, extra_args=None,
                                            **kwargs):

        return oauth2.Client.construct_RefreshAccessTokenRequest(self, request,
                                                                 request_args,
                                                                 extra_args, **kwargs)

    def construct_UserInfoRequest(self, request=UserInfoRequest,
                                  request_args=None, extra_args=None,
                                  **kwargs):

        if request_args is None:
            request_args = {}

        if "access_token" in request_args:
            pass
        else:
            if "scope" not in kwargs:
                kwargs["scope"] = "openid"
            token = self.get_token(**kwargs)
            if token is None:
                raise Exception("No valid token available")

            request_args["access_token"] = token.access_token

        return self.construct_request(request, request_args, extra_args)

    #noinspection PyUnusedLocal
    def construct_RegistrationRequest(self,
                                      request=RegistrationRequest,
                                      request_args=None, extra_args=None,
                                      **kwargs):

        return self.construct_request(request, request_args, extra_args)

    #noinspection PyUnusedLocal
    def construct_RefreshSessionRequest(self,
                                        request=RefreshSessionRequest,
                                        request_args=None, extra_args=None,
                                        **kwargs):

        return self.construct_request(request, request_args, extra_args)

    def _id_token_based(self, request, request_args=None, extra_args=None,
                        **kwargs):

        if request_args is None:
            request_args = {}

        try:
            _prop = kwargs["prop"]
        except KeyError:
            _prop = "id_token"

        if _prop in request_args:
            pass
        else:
            id_token = self._get_id_token(**kwargs)
            if id_token is None:
                raise Exception("No valid id token available")

            request_args[_prop] = id_token

        return self.construct_request(request, request_args, extra_args)

    def construct_CheckSessionRequest(self,
                                      request=CheckSessionRequest,
                                      request_args=None, extra_args=None,
                                      **kwargs):

        return self._id_token_based(request, request_args, extra_args, **kwargs)

    def construct_CheckIDRequest(self, request=CheckIDRequest,
                                 request_args=None,
                                 extra_args=None, **kwargs):

        # access_token is where the id_token will be placed
        return self._id_token_based(request, request_args, extra_args,
                                    prop="access_token", **kwargs)

    def construct_EndSessionRequest(self, request=EndSessionRequest,
                                    request_args=None, extra_args=None,
                                    **kwargs):

        if request_args is None:
            request_args = {}

        if "state" in kwargs:
            request_args["state"] = kwargs["state"]
        elif "state" in request_args:
            kwargs["state"] = request_args["state"]

        #        if "redirect_url" not in request_args:
        #            request_args["redirect_url"] = self.redirect_url

        return self._id_token_based(request, request_args, extra_args, **kwargs)

    # ------------------------------------------------------------------------

    def authorization_request_info(self, request_args=None, extra_args=None,
                                   **kwargs):
        return self.request_info(AuthorizationRequest, "GET",
                                 request_args, extra_args, **kwargs)

    # ------------------------------------------------------------------------

    def do_authorization_request(self, request=AuthorizationRequest,
                                 state="", body_type="", method="GET",
                                 request_args=None, extra_args=None,
                                 http_args=None,
                                 request_resp=AuthorizationResponse):

        return oauth2.Client.do_authorization_request(self, request, state,
                                                      body_type, method,
                                                      request_args,
                                                      extra_args, http_args,
                                                      request_resp)


    def do_access_token_request(self, request=AccessTokenRequest,
                                scope="", state="", body_type="json",
                                method="POST", request_args=None,
                                extra_args=None, http_args=None,
                                resp_request=AccessTokenResponse,
                                authn_method="", **kwargs):

        return oauth2.Client.do_access_token_request(self, request, scope, state,
                                                     body_type, method,
                                                     request_args, extra_args,
                                                     http_args, resp_request,
                                                     authn_method, **kwargs)

    def do_access_token_refresh(self, request=RefreshAccessTokenRequest,
                                state="", body_type="json", method="POST",
                                request_args=None, extra_args=None,
                                http_args=None,
                                resp_request=AccessTokenResponse,
                                **kwargs):

        return oauth2.Client.do_access_token_refresh(self, request, state,
                                                     body_type, method,
                                                     request_args,
                                                     extra_args, http_args,
                                                     resp_request, **kwargs)

    def do_registration_request(self, request=RegistrationRequest,
                                scope="", state="", body_type="json",
                                method="POST", request_args=None,
                                extra_args=None, http_args=None,
                                resp_request=RegistrationResponse):

        url, body, ht_args, csi = self.request_info(request, method=method,
                                                    request_args=request_args,
                                                    extra_args=extra_args,
                                                    scope=scope, state=state)

        if http_args is None:
            http_args = ht_args
        else:
            http_args.update(http_args)

        response = self.request_and_return(url, resp_request, method, body,
                                           body_type, state=state,
                                           http_args=http_args)

        #        if isinstance(response, Message):
        #            if "token_endpoint_auth_type" not in response:
        #                response["token_endpoint_auth_type"] = "client_secret_basic"

        return response

    def do_check_session_request(self, request=CheckSessionRequest,
                                 scope="",
                                 state="", body_type="json", method="GET",
                                 request_args=None, extra_args=None,
                                 http_args=None,
                                 resp_request=IdToken):

        url, body, ht_args, csi = self.request_info(request, method=method,
                                                    request_args=request_args,
                                                    extra_args=extra_args,
                                                    scope=scope, state=state)

        if http_args is None:
            http_args = ht_args
        else:
            http_args.update(http_args)

        return self.request_and_return(url, resp_request, method, body,
                                       body_type, state=state,
                                       http_args=http_args)

    def do_check_id_request(self, request=CheckIDRequest, scope="",
                            state="", body_type="json", method="GET",
                            request_args=None, extra_args=None,
                            http_args=None,
                            resp_request=IdToken):

        url, body, ht_args, csi = self.request_info(request, method=method,
                                                    request_args=request_args,
                                                    extra_args=extra_args,
                                                    scope=scope, state=state)

        if http_args is None:
            http_args = ht_args
        else:
            http_args.update(http_args)

        return self.request_and_return(url, resp_request, method, body,
                                       body_type, state=state,
                                       http_args=http_args)

    def do_end_session_request(self, request=EndSessionRequest, scope="",
                               state="", body_type="", method="GET",
                               request_args=None, extra_args=None,
                               http_args=None, resp_request=None):

        url, body, ht_args, csi = self.request_info(request, method=method,
                                                    request_args=request_args,
                                                    extra_args=extra_args,
                                                    scope=scope, state=state)

        if http_args is None:
            http_args = ht_args
        else:
            http_args.update(http_args)

        return self.request_and_return(url, resp_request, method, body,
                                       body_type, state=state,
                                       http_args=http_args)

    def user_info_request(self, method="GET", state="", scope="", **kwargs):
        uir = UserInfoRequest()
        if "token" in kwargs:
            if kwargs["token"]:
                uir["access_token"] = kwargs["token"]
                token = Token()
                token.type = "Bearer"
                token.access_token = kwargs["token"]
                kwargs["behavior"] = "use_authorization_header"
            else:
                # What to do ? Need a callback
                token = None
        else:
            token = self.grant[state].get_token(scope)

            if token.is_valid():
                uir["access_token"] = token.access_token
            else:
                # raise oauth2.OldAccessToken
                if self.log:
                    self.log.info("do access token refresh")
                try:
                    self.do_access_token_refresh(token=token)
                    token = self.grant[state].get_token(scope)
                    uir["access_token"] = token.access_token
                except Exception:
                    raise

        try:
            uir["request"] = kwargs["request"]
        except KeyError:
            pass

        uri = self._endpoint("userinfo_endpoint", **kwargs)
        # If access token is a bearer token it might be sent in the
        # authorization header
        # 3-ways of sending the access_token:
        # - POST with token in authorization header
        # - POST with token in message body
        # - GET with token in authorization header
        if "behavior" in kwargs:
            _behav = kwargs["behavior"]
            # use_authorization_header, token_in_message_body
            if "use_authorization_header" in _behav and token.type == "Bearer":
                if "headers" in kwargs:
                    kwargs["headers"].append(("Authorization", token.access_token))
                else:
                    kwargs["headers"] = [("Authorization", token.access_token)]
            if not "token_in_message_body" in _behav:
                # remove the token from the request
                uir["access_token"] = None

        path, body, kwargs = self.get_or_post(uri, method, uir, **kwargs)

        h_args = dict([(k, v) for k,v in kwargs.items() if k in HTTP_ARGS])

        return path, body, method, h_args

    def do_user_info_request(self, method="POST", state="", scope="openid",
                             request="openid", **kwargs):

        kwargs["request"] = request
        path, body, method, h_args = self.user_info_request(method, state,
                                                            scope, **kwargs)

        try:
            resp = self.http_request(path, method, body, **h_args)
        except oauth2.MissingRequiredAttribute:
            raise

        if resp.status_code == 200:
            assert "application/json" in resp.headers["content-type"]
        elif resp.status_code == 500:
            raise Exception("ERROR: Something went wrong: %s" % resp.text)
        else:
            raise Exception("ERROR: Something went wrong [%s]" % resp.status_code)

        return OpenIDSchema().from_json(txt=resp.text)


    def provider_config(self, issuer, keys=True, endpoints=True):
        if issuer.endswith("/"):
            _issuer = issuer[:-1]
        else:
            _issuer = issuer

        url = OIDCONF_PATTERN % _issuer

        r = self.http_request(url)
        if r.status_code == 200:
            pcr = ProviderConfigurationResponse().from_json(r.text)
        else:
            raise Exception("%s" % r.status_code)

        if "issuer" in pcr:
            if pcr["issuer"].endswith("/"):
                _pcr_issuer = pcr["issuer"][:-1]
            else:
                _pcr_issuer = pcr["issuer"]

            try:
                assert _issuer == _pcr_issuer
            except AssertionError:
                raise Exception("provider info issuer mismatch '%s' != '%s'" % (
                    _issuer, _pcr_issuer))

        if endpoints:
            for key, val in pcr.items():
                if key.endswith("_endpoint"):
                    setattr(self, key, val)

        if keys:
            self.keystore.load_keys(pcr, _issuer)

        return pcr

    def unpack_aggregated_claims(self, userinfo):
        if userinfo._claim_sources:
            for csrc, spec in userinfo._claim_sources.items():
                if "JWT" in spec:
                    if not csrc in self.keystore:
                        self.provider_config(csrc, endpoints=False)

                    keycol = self.keystore.pairkeys(csrc)["verify"]
                    info = json.loads(jwt.verify(str(spec["JWT"]), keycol))
                    attr = [n for n, s in userinfo._claim_names.items() if s ==
                                                                           csrc]
                    assert attr == info.keys()

                    for key, vals in info.items():
                        userinfo[key] = vals

        return userinfo

    def fetch_distributed_claims(self, userinfo, callback=None):
        for csrc, spec in userinfo._claim_sources.items():
            if "endpoint" in spec:
                #pcr = self.provider_config(csrc, keys=False, endpoints=False)

                if "access_token" in spec:
                    _uinfo = self.do_user_info_request(
                        token=spec["access_token"],
                        userinfo_endpoint=spec["endpoint"])
                else:
                    _uinfo = self.do_user_info_request(token=callback(csrc),
                                                       userinfo_endpoint=spec["endpoint"])

                attr = [n for n, s in userinfo._claim_names.items() if s ==
                                                                       csrc]
                assert attr == _uinfo.keys()

                for key, vals in _uinfo.items():
                    userinfo[key] = vals

        return userinfo

#noinspection PyMethodOverriding
class Server(oauth2.Server):
    def __init__(self, jwt_keys=None, ca_certs=None):
        oauth2.Server.__init__(self, jwt_keys, ca_certs)

    def _parse_urlencoded(self, url=None, query=None):
        if url:
            parts = urlparse.urlparse(url)
            scheme, netloc, path, params, query, fragment = parts[:6]

        return urlparse.parse_qs(query)

    def parse_token_request(self, request=AccessTokenRequest,
                            body=None):
        return oauth2.Server.parse_token_request(self, request, body)

    def parse_authorization_request(self, request=AuthorizationRequest,
                                    url=None, query=None):
        return oauth2.Server.parse_authorization_request(self, request, url,
                                                         query)

    def parse_jwt_request(self, request=AuthorizationRequest, txt="",
                          keys=None, verify=True):

        return oauth2.Server.parse_jwt_request(self, request, txt, keys, verify)

    def parse_refresh_token_request(self,
                                    request=RefreshAccessTokenRequest,
                                    body=None):
        return oauth2.Server.parse_refresh_token_request(self, request, body)

    def _deser_id_token(self, str=""):
        if not str:
            return None

        # have to start decoding the jwt without verifying in order to find
        # out which key to verify the JWT signature with
        _ = json.loads(jwt.unpack(str)[1])

        # in there there should be information about the client_id
        # Use that to find the key and do the signature verify

        keys = self.keystore.get_keys("verify", owner=None)

        return IdToken().from_jwt(str, key=keys)

    def parse_check_session_request(self, url=None, query=None):
        """

        """
        param = self._parse_urlencoded(url, query)
        assert "id_token" in param # ignore the rest
        return self._deser_id_token(param["id_token"][0])

    def parse_check_id_request(self, url=None, query=None):
        """

        """
        param = self._parse_urlencoded(url, query)
        assert "access_token" in param # ignore the rest
        return self._deser_id_token(param["access_token"][0])

    def _parse_request(self, request, data, format):
        if format == "json":
            request = request().from_json(data)
        elif format == "urlencoded":
            if '?' in data:
                parts = urlparse.urlparse(data)
                scheme, netloc, path, params, query, fragment = parts[:6]
            else:
                query = data
            request = request().from_urlencoded(query)
        else:
            raise Exception("Unknown package format: '%s'" %  format)

        request.verify()
        return request

    def parse_open_id_request(self, data, format="urlencoded"):
        return self._parse_request(OpenIDRequest, data, format)

    def parse_user_info_request(self, data, format="urlencoded"):
        return self._parse_request(UserInfoRequest, data, format)

    def parse_refresh_session_request(self, url=None, query=None):
        if url:
            parts = urlparse.urlparse(url)
            scheme, netloc, path, params, query, fragment = parts[:6]

        return RefreshSessionRequest().from_urlencoded(query)

    def parse_registration_request(self, data, format="urlencoded"):
        return self._parse_request(RegistrationRequest, data, format)

    def parse_end_session_request(self, query, format="urlencoded"):
        esr = self._parse_request(EndSessionRequest, query,
                                  format)
        # if there is a id_token in there it is as a string
        esr["id_token"] = self._deser_id_token(esr["id_token"])
        return esr

    def parse_issuer_request(self, info, format="urlencoded"):
        return self._parse_request(IssuerRequest, info, format)

    def make_id_token(self, session, loa="2", info_log=None, issuer="",
                      signature="symmetric", code=None, access_token=None):
        #defaults
        inawhile = {"days": 1}
        # Handle the idtoken_claims
        extra = {}
        try:
            oidreq = OpenIDRequest.deserialize(session["oidreq"], "json")
            itc = oidreq["id_token"]
            info_log("ID Token claims: %s" % itc.to_dict())
            try:
                inawhile = {"seconds": itc["max_age"]}
            except KeyError:
                inawhile = {}
            if "claims" in itc:
                for key, val in itc["claims"].items():
                    if key == "auth_time":
                        extra["auth_time"] = time_util.utc_time_sans_frac()
                    elif key == "acr":
                        #["2","http://id.incommon.org/assurance/bronze"]
                        extra["acr"] = verify_acr_level(val, loa)
        except KeyError:
            pass

        _args = {}
        if code:
            _args["c_hash"] = jwt.left_hash(code, "HS256")
        if access_token:
            _args["at_hash"] = jwt.left_hash(access_token, "HS256")

        idt = IdToken(iss=issuer, user_id=session["user_id"],
                      aud = session["client_id"],
                      exp = time_util.epoch_in_a_while(**inawhile), acr=loa,
                      **_args)

        for key, val in extra.items():
            idt[key] = val

        if "nonce" in session:
            idt.nonce = session["nonce"]

        # sign with clients secret key
        _keystore = self.keystore
        if signature == "symmetric":
            ckey = _keystore.get_keys("sign", owner=session["client_id"])
        else: # own asymmetric key
            ckey = _keystore.get_sign_key()

        if info_log:
            info_log("Sign idtoken with '%s'" % ckey)

        return idt.to_jwt(key=ckey)