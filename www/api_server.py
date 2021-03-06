'''
Created on 2018-8-27

@author: 27136
'''
import asyncio,functools,os,inspect,logging

from urllib import parse

from aiohttp import web

from api_err import APIError

def get(path):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args,**kw):
            return func(*args,**kw)
        wrapper.__method__ = 'GET'
        wrapper.__route__ =path
        return wrapper
        
    return decorator

def post(path):
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args,**kw):
            return func(*args,**kw)
        wrapper.__method__ = 'POST'
        wrapper.__route__ = path
        return wrapper
        
    return decorator

def get_required_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name,param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)
    return tuple(args)
    
def get_named_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name,param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)    

def has_named_kw_args(fn):
    params = inspect.signature(fn).parameters
    for name,param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True

def has_var_kw_arg(fn):
    params = inspect.signature(fn).parameters
    for name,param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True

def has_request_arg(fn):
    sig = inspect.signature(fn)
    params = sig.parameters
    found = False
    for name,param in params.items():
        if name == 'request':
            found = True
            continue
        if found and (param.kind != inspect.Parameter.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY and param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError('request parameter must be the last named parameter in function: %s%s'%(fn.__name__,str(sig)))
    return found

#自定义错误处理页面
def error_url(app,request,status):
    kw = {
        'status':status,
    }
    logging.error('Can not access as:%s->%s'%(request.method,request.path))
    resp = web.Response(body=app['__templating__'].get_template('error.html').render(**kw).encode('utf-8'))
    resp.content_type = 'text/html;charset=utf-8'
    return resp

#自定义api错误
def error_api(request,dt):
    logging.error('Can not access as:%s->%s  error-message:%s'%(request.method,request.path,dt.get('message',None)))
    return dt

class RequestHander(object):
    
    def __init__(self,app,fn):
        self._app = app
        self._fn = fn
        self._has_request_arg = has_request_arg(fn)
        self._has_var_kw_arg = has_var_kw_arg(fn)
        self._has_named_kw_args = has_named_kw_args(fn)
        self._get_named_kw_args = get_named_kw_args(fn)
        self._get_required_kw_args = get_required_kw_args(fn)
    
    async def __call__(self,request):
        kw = None
        if self._has_request_arg or self._has_var_kw_arg or self._has_named_kw_args:
            if request.method == 'POST':
                if not request.content_type:
                    dt={
                        'status':-1,
                        'data':None,
                        'message':'Missing content-type'
                    }
                    return error_api(request, dt)
                ct = request.content_type.lower()
                if ct.startswith('application/json'):
                    params = await request.json()
                    if not isinstance(params, dict):
                        dt={
                            'status':-1,
                            'data':None,
                            'message':'json body must be object'
                        }
                        return error_api(request, dt)
                    kw = params
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    params = await request.post()
                    kw = dict(**params)
                else:
                    dt={
                        'status':-1,
                        'data':None,
                        'message':'Unsupported Content-Type:%s'%request.content_type
                    }
                    return error_api(request, dt)
            
            if request.method == 'GET':
                qs = request.query_string
                if qs:
                    kw = dict()
                    for k,v in parse.parse_qs(qs, True).items():
                        kw[k] = v[0]
        if kw is None:
            kw = dict(**request.match_info)
        else:
            #获取已命名命名的kw
            if not self._has_var_kw_arg and self._get_named_kw_args:
                copy = dict()
                for name in self._get_named_kw_args:
                    if name in kw:
                        copy[name] = kw[name]
                kw = copy
            #检查方法参数是否与请求参数重叠,并覆盖其值
            for k,v in request.match_info.items():
                if k in kw:
                    logging.info('Duplicate arg name in named arg and kw args: %s' % k)
                kw[k] = v
        if self._has_request_arg:
            kw['request'] = request
        #check required kw
        if self._has_request_arg:
            for name in self._get_required_kw_args:
                if not name in kw:
                    dt={
                        'status':-1,
                        'data':None,
                        'message':'Missing someone argument'
                    }
                    return error_api(request, dt)
        logging.info('call arguments%s'%str(kw))
        
        try:
            r = await self._fn(**kw)
            return r
        except APIError as e:
            return dict(error=e.error,data=e.data,message=e.message)


def add_static(app,route,*fileNames):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),*fileNames)
    app.router.add_static(route,path)
    logging.info('add static path %s => %s'%(route,path))
	
# def add_mixMall_static(app):
#     path = os.path.join(os.path.dirname(os.path.abspath(__file__)),'static','mix-mall')
#     app.router.add_static('/mix-mall/',path)

def add_route(app,fn):
    method = getattr(fn, '__method__',None)
    route = getattr(fn, '__route__',None)
    if route is None or method is None:
        raise ValueError('@get or @post not defined in %s.'%(str(fn)))
    if not asyncio.iscoroutinefunction(fn) and not inspect.isgeneratorfunction(fn):
        fn = asyncio.coroutine(fn)
    logging.info('add route %s %s => %s(%s)'%(method,route,fn.__name__,', '.join(inspect.signature(fn).parameters.keys())))
    app.router.add_route(method,route,RequestHander(app,fn))
    
def add_routes(app,module_name):
    n = module_name.find('.')
    if n == (-1):
        mod = __import__(module_name, globals=globals(), locals=locals())
    else:
        name = module_name[n+1:]
        mod = getattr(__import__(module_name[:n],globals(),locals(),[name]), name)
    for attr in dir(mod):
        if attr.startswith('-'):
            continue
        fn = getattr(mod, attr)
        if callable(fn):
            method = getattr(fn, '__method__',None)
            route = getattr(fn, '__route__',None)
            if method and route:
                add_route(app, fn)
