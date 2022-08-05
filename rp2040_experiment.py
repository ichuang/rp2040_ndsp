from artiq.experiment import *

class DummyNDSP(EnvExperiment):

    def build(self):
        self.setattr_device("rp2040")

    def run(self):
        result = self.rp2040.ping()
        print("ping = ", result) 

        ret = self.rp2040.add(3, 15)
        print("add result = ", ret)

        # flash LED blue for a moment
        self.rp2040.led(0, 0, 255) # r, g, b
        self.rp2040.led(0, 0, 0)   # r, g, b

