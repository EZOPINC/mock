from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import RedirectURLMixin
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import FormView, TemplateView
from .forms import RegistrationForm
from .dashboard import dashboard_context


@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters("password1", "password2"), name="dispatch")
class RegisterView(RedirectURLMixin, FormView):
    template_name = "accounts/register.html"
    form_class = RegistrationForm
    next_page = "accounts:profile"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("accounts:profile")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        return super().get_context_data(next=self.get_redirect_url(), **kwargs)

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        messages.success(self.request, "Your account has been created. Welcome!")
        return redirect(self.get_success_url())


@method_decorator(never_cache, name="dispatch")
class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/profile.html"


@method_decorator(never_cache, name="dispatch")
class LearningSpaceView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/learning_space.html"

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | dashboard_context(self.request.user)
