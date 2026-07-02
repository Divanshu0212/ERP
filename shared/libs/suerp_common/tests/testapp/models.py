from django.db import models

from suerp_common.tenancy import TenantModel


class Widget(TenantModel):
    name = models.CharField(max_length=50)

    class Meta:
        app_label = "testapp"
