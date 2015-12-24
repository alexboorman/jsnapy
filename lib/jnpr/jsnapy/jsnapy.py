#!/usr/bin/python
import sys
import os
import shutil
import textwrap
import argparse
import yaml
from jnpr.jsnapy.snap import Parser
from jnpr.jsnapy.check import Comparator
from jnpr.jsnapy.notify import Notification
from threading import Thread
from jnpr.junos import Device
from jnpr.jsnapy import version
import colorama
import getpass
import logging
import setup_logging
import configparser
logging.getLogger("paramiko").setLevel(logging.WARNING)

class SnapAdmin:

    # need to call this function to initialize logging
    setup_logging.setup_logging()

    # taking parameters from command line
    def __init__(self):
        colorama.init(autoreset=True)
        self.config = configparser.ConfigParser()
        self.config.read(os.path.join('/etc','jsnapy','jsnapy.cfg'))
        self.logger = logging.getLogger(__name__)
        self.parser = argparse.ArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description=textwrap.dedent('''\
                                        Tool to capture snapshots and compare them
                                        It supports five subcommands:
                                         --snap, --check, --snapcheck, --diff
                                        1. Take snapshot:
                                                jsnapy --snap pre_snapfile -f main_configfile
                                        2. Compare snapshots:
                                                jsnapy --check post_snapfile pre_snapfile -f main_configfile
                                        3. Compare current configuration:
                                                jsnapy --snapcheck snapfile -f main_configfile
                                        4. Take diff without specifying test case:
                                                jsnapy --diff pre_snapfile post_snapfile -f main_configfile
                                            '''),
            usage="\n This tool enables you to capture and audit runtime environment snapshots of your "
            "networked devices running the Junos operating system (Junos OS)\n")

        group = self.parser.add_mutually_exclusive_group()
        # for mutually exclusive gp, can not use two or more options at a time
        group.add_argument(
            '--snap',
            action='store_true',
            help="take the snapshot for commands specified in test file")
        group.add_argument(
            '--check',
            action='store_true',
            help=" compare pre and post snapshots based on test operators specified in test file")
        group.add_argument(
            '--snapcheck',
            action='store_true',
            help='check current snapshot based on test file')

      #########
      ## will supoort it later
      ## for windows
      ########
      #  group.add_argument(
      #      "--init",
      #      action="store_true",
      #      help="generate init folders: snapshots, configs and main.yml",
      #  )
      #########

        group.add_argument(
            "--diff",
            action="store_true",
            help="display difference between two snapshots"
        )
        group.add_argument(
            "--version",
            action="store_true",
            help="displays version"
        )

        self.parser.add_argument(
            "pre_snapfile",
            nargs='?',
            help="pre snapshot filename")       # make it optional
        self.parser.add_argument(
            "post_snapfile",
            nargs='?',
            help="post snapshot filename",
            type=str)       # make it optional
        self.parser.add_argument(
            "-f", "--file",
            help="config file to take snapshot",
            type=str)
        self.parser.add_argument("-t", "--hostname", help="hostname", type=str)
        self.parser.add_argument(
            "-p",
            "--passwd",
            help="password to login",
            type=str)
        self.parser.add_argument(
            "-l",
            "--login",
            help="username to login",
            type=str)
       # self.parser.add_argument(
       #     "-m",
       #     "--mail",
       #     help="mail result to given id",
       #     type=str)
        #self.parser.add_argument(
        #    "-o",
        #    "--overwrite",
        #    action='store_true',
        #    help="overwrite directories and files generated by init",
        #)

        self.args = self.parser.parse_args()
        
	self.db = dict()
        self.db['store_in_sqlite'] = False
        self.db['check_from_sqlite'] = False
        self.db['db_name'] = ""
        self.db['first_snap_id'] = None
        self.db['second_snap_id'] = None

    # generate init folder, will support it later
    '''
    def generate_init(self):
       """ 
        create snapshots and configs folder along with sample main config file.
        All snapshots generated will go in snapshots folder. configs folder will contain
        all the yaml file apart from main, like device.yml, bgp_neighbor.yml
        :return:
       """

        mssg = "Creating Jsnapy directory structure at: ", os.getcwd() 
        self.logger.debug(colorama.Fore.BLUE + mssg)
        if not os.path.isdir("snapshots"):
            os.mkdir("snapshots")
        dst_config_path = os.path.join(os.getcwd(), 'configs')
         overwrite files if given option -o or --overwrite
        if not os.path.isdir(dst_config_path) or self.args.overwrite is True:
            distutils.dir_util.copy_tree(os.path.join(os.path.dirname(__file__), 'configs'),
                                         dst_config_path)
        dst_main_yml = os.path.join(dst_config_path, 'main.yml')
        if not os.path.isfile(
                os.path.join(os.getcwd(), 'main.yml')) or self.args.overwrite is True:
            shutil.copy(dst_main_yml, os.getcwd())

        logging_yml_file = os.path.join(
            os.path.dirname(__file__),
            'logging.yml')
        if not os.path.isfile(
                os.path.join(os.getcwd(), 'logging.yml')) or self.args.overwrite is True:
            shutil.copy(logging_yml_file, os.getcwd())
        mssg1= "Successfully created Jsnap directories at:",os.getcwd()
        self.logger.info(colorama.Fore.BLUE + mssg1)
    '''

    # call hosts class, connect hosts and get host list
    # use pre_snapfile because always first file is pre_snapfile regardless of
    # its name
    def get_hosts(self):
        """
        Reads the yaml config file given by user and pass the extracted data to login function to
        read device details and connect them. Also checks sqlite key to check if user wants to
        create database for snapshots
        :return:
        """
        if self.args.pre_snapfile is not None:
            output_file = self.args.pre_snapfile
        else:
            output_file = ""
        conf_file = self.args.file
        if os.path.isfile(conf_file):
            config_file = open(conf_file, 'r')
            self.main_file = yaml.load(config_file)
        elif os.path.isfile(os.path.join((self.config['DEFAULT'].get('config_file_path','/etc/jsnapy')).encode('utf-8') , conf_file)):
            fpath= (self.config['DEFAULT'].get('config_file_path','/etc/jsnapy')).encode('utf-8')
            config_file = open(os.path.join(fpath , conf_file), 'r')
            self.main_file = yaml.load(config_file)
        else:
            self.logger.error(
                colorama.Fore.RED +
                "ERROR!! file path '%s' for main config file is not correct" %
                conf_file)
            sys.exit(-1)

        compare_from_id = False
        if self.main_file.__contains__(
                'sqlite') and self.main_file['sqlite'] and self.main_file['sqlite'][0]:
            d = self.main_file['sqlite'][0]
            if d.__contains__('store_in_sqlite'):
                self.db['store_in_sqlite'] = d['store_in_sqlite']
            if d.__contains__('check_from_sqlite'):
                self.db['check_from_sqlite'] = d['check_from_sqlite']
            check = self.args.check or self.args.diff
            snap = self.args.snap or self.args.snapcheck

            if (self.db['store_in_sqlite'] and snap) or (
                    self.db['check_from_sqlite'] and check):
                if d.__contains__('database_name'):
                    self.db['db_name'] = d['database_name']
                else:
                    self.logger.info(
                        colorama.Fore.BLUE +
                        "Specify name of the database.")
                    exit(1)
                if check is True:
                    if 'compare' in d.keys() and d['compare'] is not None:
                        strr = d['compare']

                        if not isinstance(strr, str):
                            self.logger.error(colorama.Fore.RED + "Properly specify ids of first and second snapshot in format"
                                              ": first_snapshot_id, second_snapshot_id")
                            exit(1)

                        compare_from_id = True
                        lst = [val.strip() for val in strr.split(',')]

                        try:
                            lst = [int(x) for x in lst]
                        except ValueError as e:
                            self.logger.error(colorama.Fore.RED + "Properly specify id numbers of first and second snapshots"
                                              " in format: first_snapshot_id, second_snapshot_id")
                            exit(1)

                        if len(lst) > 2:
                            self.logger.error(colorama.Fore.RED + "No. of snapshots specified is more than two."
                                              " Please specify only two snapshots.")
                            exit(1)

                        if len(lst) == 2 and isinstance(
                                lst[0], int) and isinstance(lst[1], int):
                            self.db['first_snap_id'] = lst[0]
                            self.db['second_snap_id'] = lst[1]
                        else:
                            self.logger.error (colorama.Fore.RED + "Properly specify id numbers of first and second snapshots"
                                                " in format: first_snapshot_id, second_snapshot_id")

                            exit(1)
        if self.db['check_from_sqlite'] is False or compare_from_id is False:
            if (self.args.check is True and (
                    self.args.pre_snapfile is None or self.args.post_snapfile is None or self.args.file is None) or
                self.args.diff is True and (
                    self.args.pre_snapfile is None or self.args.post_snapfile is None or self.args.file is None)):
                self.logger.debug(
                    colorama.Fore.RED +
                    "Arguments not given correctly, Please refer below help message")
                self.parser.print_help()
                sys.exit(1)
        self.login(output_file)

    # call to generate snap files
    def generate_rpc_reply(self, dev, output_file, hostname, username, config_data):
        """
        Generates rpc-reply based on command/rpc given and stores them in snap_files

        :param dev: device handler
        :param snap_files: filename to store snapshots
        :param username: username to connect to device
        :return:
        """
        test_files = []
        print "\n config_data in generate_rpc_reply is: ", config_data, config_data['tests']
        for tfile in config_data['tests']:
            if not os.path.isfile(tfile):
                tfile = os.path.join((self.config['DEFAULT'].get('test_file_path','/etc/jsnapy/testfiles')).encode('utf-8'), tfile)
            if os.path.isfile(tfile):
                test_file = open(tfile, 'r')
                test_files.append(yaml.load(test_file))
            else:
                self.logger.error(
                    colorama.Fore.RED +
                    "ERROR!! File %s is not found" %
                    tfile)
        g = Parser()
        for tests in test_files:
            g.generate_reply(tests, dev, output_file, hostname, self.db, username)

    # called by check and snapcheck argument, to compare snap files
    def compare_tests(self, hostname, config_data, pre_snap=None, post_snap=None, action=None):
        """
        calls the function to compare snapshots based on arguments given
        (--check, --snapcheck, --diff)
        :param hostname: device name
        :return:
        """
        comp = Comparator()
        chk = self.args.check
        diff = self.args.diff
        pre_snap_file = self.args.pre_snapfile if pre_snap is None else pre_snap
        if (chk or diff or action in ["check", "diff"]):
            post_snap_file = self.args.post_snapfile if post_snap is None else post_snap
            test_obj = comp.generate_test_files(
                config_data,
                hostname,
                chk,
                diff,
                self.db,
                pre_snap_file,
                post_snap_file,
                action)
        else:
            test_obj = comp.generate_test_files(
                config_data,
                hostname,
                chk,
                diff,
                self.db,
                pre_snap_file,
                action)
        return test_obj

    def login(self, output_file):
        """
        Extract device information from main config file. Stores device information and call connect function,
        device can be single or multiple. Instead of connecting to all devices mentioned in yaml file, user can
        connect to some particular group of devices also.
        :param output_file: name of snapshot file
        :return:
        """
        self.host_list = []
        if self.args.hostname is None:
            k = self.main_file['hosts'][0]
            # when group of devices are given, searching for include keyword in
            # hosts in main.yaml file
            if k.__contains__('include'):
                file_tag = k['include']
                if os.path.isfile(file_tag):
                    lfile = file_tag
                else: 
                    lfile = os.path.join((self.config['DEFAULT'].get('test_file_path','/etc/jsnapy/testfiles')).encode('utf-8'), file_tag)
                login_file = open(lfile, 'r')
                dev_file = yaml.load(login_file)
                gp = k.get('group', 'all')

                dgroup = [i.strip() for i in gp.split(',')]
                for dgp in dev_file:
                    if dgroup[0].lower() == 'all' or dgp in dgroup:
                        for val in dev_file[dgp]:
                            hostname = val.keys()[0]
                            self.host_list.append(hostname)
                            username = val.get(hostname).get('username')
                            password = val.get(hostname).get('passwd')
                            t = Thread(
                                target=self.connect,
                                args=(
                                    hostname,
                                    username,
                                    password,
                                    output_file,
                                ))
                            t.start()
                            t.join()

        # login credentials are given in main config file, can connect to only
        # one device
            else:
                hostname = k.get('devices')
                username = k.get('username') or raw_input(
                    "\n Enter user name: ")
                password = k.get('passwd') or getpass.getpass(
                    "\nPlease enter password to login to Device: ")
                self.host_list.append(hostname)
                self.connect(hostname, username, password, output_file)

        # login credentials are given from command line
        else:
            hostname = self.args.hostname
            username = self.args.login if self.args.login is not None else raw_input(
                "\n Enter user name: ")
            password = self.args.passwd if self.args.passwd is not None else getpass.getpass(
                "\nPlease enter password for login to Device: ")
            self.host_list.append(hostname)
            self.connect(hostname, username, password, output_file)

    # function to connect to device
    def connect(self, hostname, username, password, snap_file, config_data= None, action= None, post_snap= None):
        """
        connect to device and calls the function either to generate snapshots
        or compare them based on option given (--snap, --check, --snapcheck, --diff)
        :param hostname: ip/ hostname of device
        :param username: username of device
        :param password: password to connect to device
        :param snap_files: file name to store snapshot
        :return:
        """

        if config_data is None:
            config_data = self.main_file

        if self.args.snap is True or self.args.snapcheck is True or action in ["snap", "snapcheck"]:
            self.logger.info(
                colorama.Fore.BLUE +
                "Connecting to device %s ................" %
                hostname)
            dev = Device(host=hostname, user=username, passwd=password, gather_facts= False)
            try:
                dev.open()
            except Exception as ex:
                self.logger.error("\nERROR occurred %s" % str(ex))
                return
            else:
                self.generate_rpc_reply(dev, snap_file, hostname, username, config_data)
                res = dev.close()

        if self.args.check is True or self.args.snapcheck is True or self.args.diff is True or action in ["check", "snapcheck"]:
            if config_data.get("mail") and self.args.diff is not True:
                mfile = os.path.join((self.config['DEFAULT'].get('test_file_path','/etc/jsnapy/testfiles')).encode('utf-8'), config_data.get('mail')) \
                    if os.path.isfile(config_data('mail')) is False else config_data('mail')
                if os.path.isfile(mfile):
                    mail_file = open(mfile, 'r')
                    mail_file = yaml.load(mail_file)
                    if "passwd" not in mail_file:
                        passwd = getpass.getpass(
                            "Please enter ur email password ")
                    else:
                        passwd = mail_file['passwd']
                    res = self.compare_tests(hostname, config_data,snap_file, post_snap, action)
                    send_mail = Notification()
                    send_mail.notify(mail_file, hostname, passwd, testobj)
                else:
                    self.logger.error(
                        colorama.Fore.RED +
                        "ERROR!! Path of file containing mail content is not correct")
            else:
                res = self.compare_tests(hostname, config_data, snap_file, post_snap, action)
        return res

    ############################### functions to support module #######################################################

    def extract_data(self, file_name, config_data):
        if os.path.isfile(config_data):
            data = open(config_data, 'r')
            config_data = yaml.load(data)
            print config_data
        elif type(config_data) is str:
            print "insid elif"
            config_data = yaml.load(config_data)
            print config_data
        else:
            print "incorrect config file or data, please chk !!!!"
            exit(-1)
        k = config_data.get('hosts')[0]
        hostname = k.get('devices')
        username = k.get('username') or raw_input("\n Enter user name: ")
        password = k.get('passwd') or getpass.getpass("\nPlease enter password to login to Device: ")
        snap_files = hostname + '_' + file_name if not os.path.isfile(file_name) else file_name
        return hostname,username,password, snap_files,config_data

    def snap(self, file_name, data, dev= None):
        hostname, username, password, snap_file, config_data = self.extract_data(file_name, data)
        self.connect(hostname, username, password, snap_file, config_data, "snap")

    def snapcheck(self, file_name, data, dev= None):
        print "\n inside snapcheck \n"
        hostname, username, password, snap_file, config_data = self.extract_data(file_name, data)
        res= self.connect(hostname, username, password, snap_file, config_data, "snapcheck")
        print "result for test case is res.result, res.no_failed, res.no_passed, res.test_details :", res.result, res.no_failed, res.no_passed, res.test_details
        return res.result

    def check(self, pre_file, post_file, data, dev= None):
        hostname, username, password, pre_snap, config_data = self.extract_data(pre_file, data)
        print "\n config_data: ", config_data
        post_snap = hostname + '_' + post_file
        print "connecting -----------"
        res = self.connect(hostname, username, password, pre_snap, config_data, "check", post_snap)
        print "result for test case is res.result, res.no_failed, res.no_passed, res.test_details :", res.result, res.no_failed, res.no_passed, res.test_details
        return res.result


    #######  generate init folder ######
    '''
    def generate_init(self):
        
        create snapshots and configs folder along with sample main config file.
        All snapshots generated will go in snapshots folder. configs folder will contain
        all the yaml file apart from main, like device.yml, bgp_neighbor.yml
        :return:
       
        mssg= "Creating Jsnapy directory structure at:" + os.getcwd()
        self.logger.debug(colorama.Fore.BLUE + mssg)
        if not os.path.isdir("snapshots"):
            os.mkdir("snapshots")
        if not os.path.isdir("logs"):
            os.mkdir("logs")
        dst_config_path = os.path.join(os.getcwd(), 'configs')
        # overwrite files if given option -o or --overwrite
        if not os.path.isdir(dst_config_path) or self.args.overwrite is True:
            distutils.dir_util.copy_tree(os.path.join(os.path.dirname(__file__), 'configs'),
                                         dst_config_path)
        dst_main_yml = os.path.join(dst_config_path, 'main.yml')
        if not os.path.isfile(
                os.path.join(os.getcwd(), 'main.yml')) or self.args.overwrite is True:
            shutil.copy(dst_main_yml, os.getcwd())

        logging_yml_file = os.path.join(
            os.path.dirname(__file__),
            'logging.yml')
        if not os.path.isfile(
                os.path.join(os.getcwd(), 'logging.yml')) or self.args.overwrite is True:
            shutil.copy(logging_yml_file, os.getcwd())
        mssg1= "Jsnap folders created at: " + os.getcwd()
        self.logger.info(colorama.Fore.BLUE + mssg1)
    '''

    def check_arguments(self):
        """
        checks combination of arguments given from command line and display help if correct
        set of combination is not given.
        :return:
        """
        if((self.args.snap is True and (self.args.pre_snapfile is None or self.args.file is None)) or
            (self.args.check is True and (self.args.file is None)) or
            (self.args.snapcheck is True and (self.args.pre_snapfile is None or self.args.file is None or self.args.post_snapfile is not None)) or
            (self.args.diff is True and self.args.file is None)
           ):
            self.logger.error(
                "Arguments not given correctly, Please refer help message")
            self.parser.print_help()
            sys.exit(1)
        else:
            pass 


def main():
    js = SnapAdmin()
    if len(sys.argv) == 1:
        js.parser.print_help()
        sys.exit(1)
    else:
        js.check_arguments()
        if js.args.version is True:
             print "Jsnapy version:",version.__version__
        else:
             js.get_hosts()

if __name__ == '__main__':
    main()
