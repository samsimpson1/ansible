from subprocess import run

class FilterModule(object):
  def filters(self):
    return {
      'amber_compile': self.amber_compile
    }
  
  def amber_compile(self, source_code):
    amber = run(
      ['amber', 'build', '-', '-'],
      input=source_code.encode('utf-8'),
      capture_output=True,
      check=True
    )

    return amber.stdout.decode('utf-8')