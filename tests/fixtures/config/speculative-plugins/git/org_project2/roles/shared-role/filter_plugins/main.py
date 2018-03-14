import subprocess


def my_cool_test(string):
    shell_output = subprocess.check_output(['hostname'])
    return 'hostname: %s' % shell_output.decode('utf-8')


class FilterModule(object):

    def filters(self):
        return {
            'my_cool_test': my_cool_test
        }
