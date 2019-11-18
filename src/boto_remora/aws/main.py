""" boto_remora.aws.main package for main objects and functions """
import dataclasses
import json
import logging
import pathlib

from collections import ChainMap
from typing import Dict, Optional, Sequence

import botocore.exceptions
import jmespath

from pkg_resources import resource_filename

from .base import AwsBaseService


_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass()
class Ec2(AwsBaseService):
    """ Object to help with EC2 """

    service_name: str = dataclasses.field(default="ec2", init=False)

    @property
    def available_regions(self):
        """
        Checks to which regions are enabled and accssible
        from: https://www.cloudar.be/awsblog/checking-if-a-region-is-enabled-using-the-aws-api/
        """
        if not self._available_regions:
            query = "Regions[].RegionName"
            response = self.client.describe_regions()
            self._available_regions = frozenset(jmespath.search(query, response))

        return self._available_regions


@dataclasses.dataclass()
class Pricing(AwsBaseService):
    """
    Object to help with pricing
    For supported regions see,
    https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-pelong.html#pe-endpoint
    """

    service_name: str = dataclasses.field(default="pricing", init=False)
    # servicecode: str = ""
    region_name: str = "us-east-1"
    filter_keys: Sequence[str] = dataclasses.field(
        default_factory=lambda: ("Field", "Value")
    )
    # currency: str = "USD"
    _region_map: Dict[str, str] = dataclasses.field(
        default_factory=dict, init=False, repr=False
    )
    _region_map_rev: Dict[str, str] = dataclasses.field(
        default_factory=dict, init=False, repr=False
    )

    @property
    def region_map(self):
        if not self._region_map:
            self._region_map = Ssm(session=self.session).get_regions()
        return self._region_map

    @property
    def region_map_rev(self):
        if not self._region_map_rev:
            self._region_map_rev = {v: k for k, v in self.region_map.items()}
        return self._region_map_rev

    def get_price_list(
        self,
        servicecode: Optional[str] = None,
        filter_kv: Optional[Dict[str, str]] = None,
    ):
        """
        Fetch from price API
        """
        filters = [
            {"Type": "TERM_MATCH", self.filter_keys[0]: k, self.filter_keys[1]: v}
            for k, v in filter_kv.items()
        ]
        response = self.client.get_products(ServiceCode=servicecode, Filters=filters)
        return response["PriceList"]

    # def filter_fmt(self, filters: Dict[str, str], filter_type="TERM_MATCH"):
    #     """
    #     Returns list formatted for pricing filter_fmt.
    #     """
    #     return [{"Type": filter_type}.update(super().filter_fmt(f)) for f in filters]


@dataclasses.dataclass()
class Ssm(AwsBaseService):
    """ Object to help with SSM """

    service_name: str = dataclasses.field(default="ssm", init=False)

    def get_regions(self):
        """

        Returns
        -------
        Dict of region short codes mapped to their long codes.
        """
        regions = self._get_region_from_boto()
        regions.update(
            map(
                self._get_region_long_name,
                set(self._get_region_short_codes()).difference(regions),
            )
        )

        return regions

    @staticmethod
    def _get_region_from_boto(partition: Optional[str] = None) -> Dict[str, str]:
        """
        Maps AWS region names to human friendly names.

        Parameters
        ----------
        partition : str, optional
            AWS partitions: aws, aws-cn, aws-us-gov, aws-iso, aws-iso-b (default "aws")

        Returns
        -------
        Dict[str, str]
            A map of region names to their human friend names.
        """
        endpoints_file = pathlib.Path(
            resource_filename("botocore", "data/endpoints.json")
        )
        jmes_search = (
            f"partitions[?partition == '{partition}'].regions"
            if partition
            else f"partitions[*].regions"
        )

        with endpoints_file.open("r") as fid:
            region_data = jmespath.search(jmes_search, json.load(fid))

        region_data = {k: v["description"] for k, v in ChainMap(*region_data).items()}

        return region_data

    def _get_region_long_name(self, short_code):
        param_name = (
            "/aws/service/global-infrastructure/regions/" f"{short_code}/longName"
        )
        response = self.client.get_parameters(Names=[param_name])
        return response["Parameters"][0]["Value"]

    def _get_region_short_codes(self):
        output = set()
        for page in self.client.get_paginator("get_parameters_by_path").paginate(
            Path="/aws/service/global-infrastructure/regions"
        ):
            output.update(p["Value"] for p in page["Parameters"])

        return output


@dataclasses.dataclass()
class Sts(AwsBaseService):
    """ Object to help with STS """

    service_name: str = dataclasses.field(default="sts", init=False)

    def is_region_accessible(self):
        """
        Checks region is accessible from a given session.
        see: https://www.cloudar.be/awsblog/checking-if-a-region-is-enabled-using-the-aws-api/
        """

        _LOGGER.debug(
            "Checking %s can access region %s", self.profile_name, self.region_name
        )
        try:
            self.client.get_caller_identity()
        except botocore.exceptions.ClientError as err:
            _LOGGER.warning(
                "Profile %s could not reach region %s. Caught exception %s.%s",
                self.profile_name,
                type(err).__name__,
                self.region_name,
                err.response["Error"]["Code"],
            )
            return False
        return True
