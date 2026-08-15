Traceback (most recent call last)

    File "C:\Users\pp\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\app.py", line 1478, in __call__

    return self.wsgi_app(environ, start_response)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    File "C:\Users\pp\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\app.py", line 1458, in wsgi_app

    response = self.handle_exception(e)
               ^^^^^^^^^^^^^^^^^^^^^^^^

    File "C:\Users\pp\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\app.py", line 1455, in wsgi_app

    response = self.full_dispatch_request()
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    File "C:\Users\pp\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\app.py", line 869, in full_dispatch_request

    rv = self.handle_user_exception(e)
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    File "C:\Users\pp\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\app.py", line 867, in full_dispatch_request

    rv = self.dispatch_request()
         ^^^^^^^^^^^^^^^^^^^^^^^

    File "C:\Users\pp\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\app.py", line 852, in dispatch_request

    return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    File "d:\asset\blueprints\auth.py", line 40, in login

    return render_template('login.html')
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    File "C:\Users\pp\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\templating.py", line 152, in render_template

    return _render(app, template, context)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    File "C:\Users\pp\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\templating.py", line 133, in _render

    rv = template.render(context)
         ^^^^^^^^^^^^^^^^^^^^^^^^

    File "C:\Users\pp\AppData\Local\Programs\Python\Python311\Lib\site-packages\jinja2\environment.py", line 1295, in render

    self.environment.handle_exception()
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    File "C:\Users\pp\AppData\Local\Programs\Python\Python311\Lib\site-packages\jinja2\environment.py", line 942, in handle_exception

    raise rewrite_traceback_stack(source=source)
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    File "d:\asset\templates\login.html", line 1, in top-level template code

    {% extends "base.html" %}

    File "d:\asset\templates\base.html", line 518, in top-level template code

    <li><a class="dropdown-item" href="{{ url_for('login') }}"><i class="fas fa-sign-in-alt"></i> 登录</a></li>

    File "C:\Users\pp\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\app.py", line 1071, in url_for

    return self.handle_url_build_error(error, endpoint, values)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    File "C:\Users\pp\AppData\Local\Programs\Python\Python311\Lib\site-packages\flask\app.py", line 1060, in url_for

    rv = url_adapter.build(  # type: ignore[union-attr]
         

    File "C:\Users\pp\AppData\Local\Programs\Python\Python311\Lib\site-packages\werkzeug\routing\map.py", line 919, in build

    raise BuildError(endpoint, values, method, self)
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    werkzeug.routing.exceptions.BuildError: Could not build url for endpoint 'login'. Did you mean 'auth.login' instead?





  1. 模板中 url_for('login') 等旧引用 — 路由现属于 auth 蓝图，已将所有模板中的 url_for('login') →
  url_for('auth.login')，url_for('logout') → url_for('auth.logout')，共修改 3 个模板文件 8 处引用。                       2. 丢失的路由 — 旧 app.py 中的 /register 和 /change_password 路由在重构时被误删。已在 blueprints/auth.py
  中重新添加这两个路由。                                                                                                