from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

from ..forms.acceso import AccesoEmpleadosForm
from ..seguridad import controlar_intentos


class AccesoView(LoginView):
    template_name = 'cafeteria/login.html'
    authentication_form = AccesoEmpleadosForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        usuario = request.POST.get('username', '')[:150]
        with controlar_intentos(usuario, request.META.get('REMOTE_ADDR', '')) as control:
            if control.bloqueado:
                form = self.get_form_class()(request=request)
                response = self.render_to_response(self.get_context_data(form=form, acceso_bloqueado=True), status=429)
                response['Retry-After'] = '900'
                return response
            if form.is_valid():
                control.correcto = True
                return self.form_valid(form)
            return self.form_invalid(form)


class SalirView(LogoutView):
    next_page = reverse_lazy('login')


def raiz(request):
    return redirect('dashboard')


@method_decorator(never_cache, name='dispatch')
class DashboardView(TemplateView):
    template_name = 'cafeteria/dashboard.html'
