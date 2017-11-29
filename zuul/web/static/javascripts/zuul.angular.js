// @licstart  The following is the entire license notice for the
// JavaScript code in this page.
//
// Copyright 2017 Red Hat
//
// Licensed under the Apache License, Version 2.0 (the "License"); you may
// not use this file except in compliance with the License. You may obtain
// a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
// WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
// License for the specific language governing permissions and limitations
// under the License.
//
// @licend  The above is the entire license notice
// for the JavaScript code in this page.

angular.module('zuulTenants', []).controller(
    'mainController', function($scope, $http)
{
    $scope.tenants = undefined;
    $scope.tenants_fetch = function() {
        $http.get("tenants.json")
            .then(function success(result) {
                $scope.tenants = result.data;
            });
    }
    $scope.tenants_fetch();
});

angular.module('zuulJobs', []).controller(
    'mainController', function($scope, $http)
{
    $scope.jobs = undefined;
    $scope.jobs_fetch = function() {
        $http.get("jobs.json")
            .then(function success(result) {
                $scope.jobs = result.data;
            });
    }
    $scope.jobs_fetch();
});

angular.module('zuulBuilds', [], function($locationProvider) {
    $locationProvider.html5Mode({
        enabled: true,
        requireBase: false
    });
}).controller('mainController', function($scope, $http, $location)
{
    $scope.rowClass = function(build) {
        if (build.result == "SUCCESS") {
            return "success";
        } else {
            return "warning";
        }
    };
    var query_args = $location.search();
    var url = $location.url();
    var tenant_start = url.lastIndexOf(
        '/', url.lastIndexOf('/builds.html') - 1) + 1;
    var tenant_length = url.lastIndexOf('/builds.html') - tenant_start;
    $scope.tenant = url.substr(tenant_start, tenant_length);
    $scope.builds = undefined;
    if (query_args["pipeline"]) {$scope.pipeline = query_args["pipeline"];
    } else {$scope.pipeline = "";}
    if (query_args["job_name"]) {$scope.job_name = query_args["job_name"];
    } else {$scope.job_name = "";}
    if (query_args["project"]) {$scope.project = query_args["project"];
    } else {$scope.project = "";}
    $scope.builds_fetch = function() {
        query_string = "";
        if ($scope.tenant) {query_string += "&tenant="+$scope.tenant;}
        if ($scope.pipeline) {query_string += "&pipeline="+$scope.pipeline;}
        if ($scope.job_name) {query_string += "&job_name="+$scope.job_name;}
        if ($scope.project) {query_string += "&project="+$scope.project;}
        if (query_string != "") {query_string = "?" + query_string.substr(1);}
        $http.get("builds.json" + query_string)
            .then(function success(result) {
                for (build_pos = 0;
                     build_pos < result.data.length;
                     build_pos += 1) {
                    build = result.data[build_pos]
                    if (build.node_name == null) {
                        build.node_name = 'master'
                    }
                    /* Fix incorect url for post_failure job */
                    if (build.log_url == build.job_name) {
                        build.log_url = undefined;
                    }
                }
                $scope.builds = result.data;
            });
    }
    $scope.builds_fetch()
});
