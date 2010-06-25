
#public symbols
__all__ = ['Assembly']


from enthought.traits.api import HasTraits, List, Instance, TraitError
from enthought.traits.api import TraitType, Undefined
from enthought.traits.trait_base import not_none

import networkx as nx
from networkx.algorithms.traversal import is_directed_acyclic_graph, strongly_connected_components

from openmdao.main.interfaces import IDriver, IWorkflow
from openmdao.main.component import Component
from openmdao.main.container import Container
from openmdao.main.dataflow import Dataflow
from openmdao.main.driver import Driver
from openmdao.main.expression import Expression
from openmdao.main.expreval import ExprEvaluator

class _undefined_(object):
    pass


def _filter_internal_edges(edges):
    """Return a copy of the given list of edges with edges removed that are
    connecting two variables on the same component.
    """
    return [(u,v) for u,v in edges
                          if u.split('.', 1)[0] != v.split('.', 1)[0]]
        
class PassthroughTrait(TraitType):
    """A trait that can use another trait for validation, but otherwise is
    just a trait that lives on an Assembly boundary and can be connected
    to other traits within the Assembly.
    """
    
    def validate(self, obj, name, value):
        if self.validation_trait:
            return self.validation_trait.validate(obj, name, value)
        return value

class Assembly (Component):
    """This is a container of Components. It understands how to connect inputs
    and outputs between its children.  When executed, it runs the top level
    Driver called 'driver'.
    """
    
    driver = Instance(Driver, allow_none=True,
                      desc="The top level Driver that manages execution of this Assembly")
    
    def __init__(self, doc=None, directory=''):
        self._child_io_graphs = {}
        self._need_child_io_update = True
        
        self.comp_graph = ComponentGraph()
        
        # this is the default Workflow for all Drivers living in this
        # Assembly that don't define their own Workflow
        self._default_workflow = Dataflow(self)
        
        # A graph of Variable names (local path), 
        # with connections between Variables as directed edges.  
        # Children are queried for dependencies between their inputs and outputs
        # so they can also be represented in the graph. 
        self._var_graph = nx.DiGraph()
        
        super(Assembly, self).__init__(doc=doc, directory=directory)
        
        # add any Variables we may have inherited from our base classes
        # to our _var_graph..
        for v in self.keys(iotype=not_none):
            if v not in self._var_graph:
                self._var_graph.add_node(v)
                
        # default Driver executes its workflow once
        self.add('driver', Driver())

    def get_var_graph(self):
        """Returns the Variable dependency graph, after updating it with child
        info if necessary.
        """
        if self._need_child_io_update:
            vargraph = self._var_graph
            childiographs = self._child_io_graphs
            for childname,val in childiographs.items():
                graph = getattr(self, childname).get_io_graph()
                if graph is not val:  # child io graph has changed
                    if val is not None:  # remove old stuff
                        vargraph.remove_nodes_from(val)
                    childiographs[childname] = graph
                    node_data = graph.nodes_iter(data=True)
                    for n,dat in node_data:
                        vargraph.add_node(n, **dat)
                    vargraph.add_edges_from(graph.edges_iter(data=True))
            self._need_child_io_update = False
        return self._var_graph
        
    #def get_io_graph(self):
        #"""For now, just return our base class version of get_io_graph."""
        ## TODO: make this return an actual graph of inputs to outputs based on 
        ##       the contents of this Assembly instead of a graph where all 
        ##       outputs depend on all inputs
        ## NOTE: if the io_graph changes, this function must return a NEW graph
        ## object instead of modifying the old one, because object identity
        ## is used in the parent assembly to determine of the graph has changed
        #return super(Assembly, self).get_io_graph()
    
    def add(self, name, obj, add_to_workflow=True):
        """Add obj to the workflow and call base class *add*.
        
        Returns the added object.
        """
        obj = super(Assembly, self).add(name, obj)
        self.comp_graph.add(obj)
        
        # add all non-Driver Components to the Assembly workflow by default
        # unless add_to_workflow is False
        if add_to_workflow is True and isinstance(obj, Component) and not isinstance(obj, Driver):
            self._default_workflow.add(obj)

        # since the internals of the given Component can change after it's
        # added, wait to collect its io_graph until we need it
        self._child_io_graphs[obj.name] = None
        self._need_child_io_update = True

        return obj
        
    def remove_container(self, name):
        """Remove the named container object from this container and remove
        it from its workflow (if any)."""
        cont = getattr(self, name)
        self._default_workflow.remove(cont)
        for obj in self.__dict__.values():
            if obj is not cont and isinstance(obj, Driver):
                obj.remove_from_workflow(cont)
            
        if name in self._child_io_graphs:
            childgraph = self._child_io_graphs[name]
            if childgraph is not None:
                self._var_graph.remove_nodes_from(childgraph)
            del self._child_io_graphs[name]
                    
        return super(Assembly, self).remove_container(name)


    def create_passthrough(self, pathname, alias=None):
        """Creates a PassthroughTrait that uses the trait indicated by
        pathname for validation (if it's not a property trait), adds it to
        self, and creates a connection between the two. If alias is *None,*
        the name of the "promoted" trait will be the last entry in its
        pathname. The trait specified by pathname must exist.
        """
        if alias:
            newname = alias
        else:
            parts = pathname.split('.')
            newname = parts[-1]

        if newname in self.__dict__:
            self.raise_exception("a trait named '%s' already exists" %
                                 newname, TraitError)
        trait, val = self._find_trait_and_value(pathname)
        if not trait:
            self.raise_exception("the trait named '%s' can't be found" %
                                 pathname, TraitError)
        iotype = trait.iotype
        # the trait.trait_type stuff below is for the case where the trait is actually
        # a ctrait (very common). In that case, trait_type is the actual underlying
        # trait object
        if (getattr(trait,'get') or getattr(trait,'set') or
            getattr(trait.trait_type, 'get') or getattr(trait.trait_type,'set')):
            trait = None  # not sure how to validate using a property
                          # trait without setting it, so just don't use it
        newtrait = PassthroughTrait(iotype=iotype, validation_trait=trait)
        self.add_trait(newname, newtrait)
        setattr(self, newname, val)

        if iotype == 'in':
            self.connect(newname, pathname)
        else:
            self.connect(pathname, newname)

        return newtrait

    def get_dyn_trait(self, pathname, iotype=None):
        """Retrieves the named trait, attempting to create a PassthroughTrait
        on-the-fly if the specified trait doesn't exist.
        """
        trait = self.trait(pathname)
        if trait is None:
            newtrait = self.create_passthrough(pathname)
            if iotype is not None and iotype != newtrait.iotype:
                self.raise_exception(
                    "new trait has iotype of '%s' but '%s' was expected" %
                    (newtrait.iotype, iotype), TraitError)
        return trait

    def split_varpath(self, path):
        """Return a tuple of compname,component,varname given a path
        name of the form 'compname.varname'. If the name is of the form 'varname'
        then compname will be None and comp is self. 
        """
        try:
            compname, varname = path.split('.', 1)
        except ValueError:
            return (None, self, path)
        
        return (compname, getattr(self, compname), varname)

    def connect(self, srcpath, destpath):
        """Connect one src Variable to one destination Variable. This could be
        a normal connection (output to input) or a passthrough connection."""

        srccompname, srccomp, srcvarname = self.split_varpath(srcpath)
        srctrait = srccomp.get_dyn_trait(srcvarname, 'out')
        destcompname, destcomp, destvarname = self.split_varpath(destpath)
        desttrait = destcomp.get_dyn_trait(destvarname, 'in')
        
        if srccompname == destcompname:
            self.raise_exception(
                'Cannot connect %s to %s. Both are on same component.' %
                                 (srcpath, destpath), RuntimeError)
        if srccomp is not self and destcomp is not self:
            # it's not a passthrough, so must connect input to output
            if srctrait.iotype != 'out':
                self.raise_exception(
                    '.'.join([srccomp.get_pathname(),srcvarname])+
                    ' must be an output variable',
                    RuntimeError)
            if desttrait.iotype != 'in':
                self.raise_exception(
                    '.'.join([destcomp.get_pathname(),destvarname])+
                    ' must be an input variable',
                    RuntimeError)
                
        if self.is_destination(destpath):
            self.raise_exception(destpath+' is already connected',
                                 RuntimeError)             
            
        # test compatability (raises TraitError on failure)
        if desttrait.validate is not None:
            try:
                if desttrait.trait_type.get_val_meta_wrapper:
                    desttrait.validate(destcomp, destvarname, 
                                       srccomp.get_wrapped_attr(srcvarname))
                else:
                    desttrait.validate(destcomp, destvarname, 
                                       getattr(srccomp, srcvarname))
            except TraitError, err:
                self.raise_exception("can't connect '%s' to '%s': %s" % 
                                     (srcpath,destpath,str(err)), TraitError)
        
        if destcomp is not self:
            destcomp.set_source(destvarname, srcpath)
            if srccomp is not self: # neither var is on boundary
                self.comp_graph.connect(srcpath, destpath)
                self._default_workflow.config_changed()
        
        vgraph = self.get_var_graph()
        vgraph.add_edge(srcpath, destpath)
            
        # invalidate destvar if necessary
        if destcomp is self and desttrait.iotype == 'out': # boundary output
            if destcomp.get_valid(destvarname) and \
               srccomp.get_valid(srcvarname) is False:
                if self.parent:
                    # tell the parent that anyone connected to our boundary
                    # output is invalid.
                    # Note that it's a dest var in this scope, but a src var in
                    # the parent scope.
                    self.parent.invalidate_deps([destpath], True)
            self.set_valid(destpath, False)
        elif srccomp is self and srctrait.iotype == 'in': # boundary input
            self.set_valid(srcpath, False)
        else:
            #destcomp.set_valid(destvarname, False)
            destcomp.invalidate_deps([destvarname], notify_parent=True)
            #self.invalidate_deps([destpath])
        
        self._io_graph = None

    def disconnect(self, varpath, varpath2=None):
        """If varpath2 is supplied, remove the connection between varpath and
        varpath2. Otherwise, if varpath is the name of a trait, remove all
        connections to/from varpath in the current scope. If varpath is the
        name of a Component, remove all connections from all of its inputs
        and outputs. 
        """
        vargraph = self.get_var_graph()
        if varpath not in vargraph:
            tup = varpath.split('.', 1)
            if len(tup) == 1 and isinstance(getattr(self, varpath), Component):
                comp = getattr(self, varpath)
                for var in comp.list_inputs():
                    self.disconnect('.'.join([varpath, var]))
                for var in comp.list_outputs():
                    self.disconnect('.'.join([varpath, var]))
            else:
                self.raise_exception("'%s' is not a linkable attribute" %
                                     varpath, RuntimeError)
            return
        
        to_remove = []
        if varpath2 is not None:
            if varpath2 in vargraph[varpath]:
                to_remove.append((varpath, varpath2))
            elif varpath in vargraph[varpath2]:
                to_remove.append((varpath2, varpath))
            else:
                self.raise_exception('%s is not connected to %s' % 
                                     (varpath, varpath2), RuntimeError)
        else:  # remove all connections from the Variable
            to_remove.extend(vargraph.edges(varpath)) # outgoing edges
            to_remove.extend(vargraph.in_edges(varpath)) # incoming
        
        for src,sink in _filter_internal_edges(to_remove):
            vtup = sink.split('.', 1)
            if len(vtup) > 1:
                getattr(self, vtup[0]).remove_source(vtup[1])
                # if its a connection between two children 
                # (no boundary connections) then remove a connection 
                # between two components in the component graph
                utup = src.split('.',1)
                if len(utup)>1:
                    self.comp_graph.disconnect(utup[0], vtup[0])
                    self._default_workflow.config_changed()
                
        vargraph.remove_edges_from(to_remove)
        
        # the io graph has changed, so have to remake it
        self._io_graph = None  


    def is_destination(self, varpath):
        """Return True if the Variable specified by varname is a destination
        according to our graph. This means that either it's an input connected
        to an output, or it's the destination part of a passthrough connection.
        """
        tup = varpath.split('.',1)
        preds = self._var_graph.pred.get(varpath, {})
        if len(tup) == 1:
            return len(preds) > 0
        else:
            start = tup[0]+'.'
            for pred in preds:
                if not pred.startswith(start):
                    return True
        return False

    def execute (self):
        """Runs driver and updates our boundary variables."""
        self.driver.run()
        self._update_boundary_vars()
    
    def _update_boundary_vars (self):
        """Update output variables on our bounary."""
        invalid_outs = self.list_outputs(valid=False)
        vgraph = self.get_var_graph()
        for out in invalid_outs:
            inedges = vgraph.in_edges(nbunch=out)
            if len(inedges) == 1:
                setattr(self, out, self.get(inedges[0][0]))

    def step(self):
        """Execute a single child component and return."""
        self.driver.step()
        
    def stop(self):
        """Stop the calculation."""
        self.driver.stop()
    
    def list_connections(self, show_passthrough=True):
        """Return a list of tuples of the form (outvarname, invarname).
        """
        if show_passthrough:
            return _filter_internal_edges(self.get_var_graph().edges())
        else:
            return _filter_internal_edges([(outname,inname) for outname,inname in 
                                           self.get_var_graph().edges_iter() 
                                           if '.' in outname and '.' in inname])

    def update_inputs(self, varnames):
        """Transfer input data to input variables on the specified component.
        The varnames iterator is assumed to contain names that include the
        component name, for example: ['comp1.a', 'comp1.b'].
        """
        updated = False  # this becomes True if we actually update any inputs
        parent = self.parent
        vargraph = self.get_var_graph()
        pred = vargraph.pred
        
        for vname in varnames:
            if vargraph.node[vname].get('expr'): # it's an expression link
                continue
            
            preds = pred.get(vname, '')
            if len(preds) == 0: 
                continue
                       
            srcname = preds.keys()[0]
            srccompname,srccomp,srcvarname = self.split_varpath(srcname)
            destcompname,destcomp,destvarname = self.split_varpath(vname)

            #if vargraph[srcname][vname].get('expr'): # it's an expression link
                #continue
            
            if len(preds) > 1:
                self.raise_exception("variable '%s' has multiple sources %s" %
                                     (vname, preds.keys()), RuntimeError)

            updated = True

            if srccomp.get_valid(srcvarname) is False:  # source is invalid 
                # need to backtrack to get a valid source value
                if srccompname is None: # a boundary var
                    if parent:
                        parent.update_inputs(['.'.join([self.name, srcname])])
                    else:
                        srccomp.set_valid(srcvarname, True) # validate source
                else:
                    srccomp.update_outputs([srcvarname])

            try:
                srcval = srccomp.get_wrapped_attr(srcvarname)
            except Exception, err:
                self.raise_exception(
                    "cannot retrieve value of source attribute '%s'" %
                    srcname, type(err))
            try:
                destcomp.set(destvarname, srcval, srcname=srcname)
            except Exception, exc:
                msg = "cannot set '%s' from '%s': %s" % (vname, srcname, exc)
                self.raise_exception(msg, type(exc))
        
        return updated

    def update_outputs(self, outnames):
        """Execute any necessary internal or predecessor components in order
        to make the specified output variables valid.
        """
        self.update_inputs(outnames)

    def get_valids(self, names):
        """Returns a list of boolean values indicating whether the named
        attributes are valid (True) or invalid (False). Entries in names may
        specify either direct traits of self or those of direct children of
        self, but no deeper in the hierarchy than that.
        """
        valids = []
        for name in names:
            if self.trait(name):
                valids.append(self.get_valid(name))
            else:
                tup = name.split('.', 1)
                if len(tup) > 1:
                    comp = getattr(self, tup[0])
                    valids.append(comp.get_valid(tup[1]))
                else:
                    self.raise_exception("get_valids: unknown variable '%s'" %
                                         name, RuntimeError)
        return valids

    def invalidate_deps(self, varnames, notify_parent=False):
        """Mark all Variables invalid that depend on varnames. Returns a list
        of our newly invalidated boundary outputs.
        """
        vargraph = self.get_var_graph()
        succ = vargraph.succ  #successor nodes in the graph
        stack = set(varnames)
        outs = []
        while len(stack) > 0:
            name = stack.pop()
            if name in vargraph:
                tup = name.split('.', 1)
                if len(tup)==1:
                    self.set_valid(name, False)
                else:
                    getattr(self, tup[0]).set_valid(tup[1], False)
            else:
                self.raise_exception("%s is not an io trait" % name,
                                     RuntimeError)
            for vname in succ.get(name, []):
                tup = vname.split('.', 1)
                if len(tup) == 1:  #boundary var or Component
                    if self.trait(vname).iotype == 'out':
                        # it's an output boundary var
                        outs.append(vname)
                else:  # a var from a child component 
                    compname, compvar = tup
                    comp = getattr(self, compname)
                    if comp.get_valid(compvar):  # node is a valid Variable
                        for newvar in comp.invalidate_deps([compvar]):
                            stack.add('.'.join([compname, newvar]))
                        stack.add(vname)
        
        if len(outs) > 0:
            for out in outs:
                self.set_valid(out, False)
            if notify_parent and self.parent:
                self.parent.invalidate_deps(
                    ['.'.join([self.name,n]) for n in outs], 
                    notify_parent)
        return outs


class ComponentGraph(object):
    """
    A dependency graph for Components.
    """

    def __init__(self):
        self._no_expr_graph = nx.DiGraph()
        
    def __contains__(self, comp):
        """Return True if this graph contains the given component."""
        return comp.name in self._no_expr_graph
    
    def subgraph(self, nodelist):
        return self._no_expr_graph.subgraph(nodelist)
    
    def graph(self):
        return self._no_expr_graph
    
    def __len__(self):
        return len(self._no_expr_graph)
        
    def iter(self, scope):
        """Iterate through the nodes in dataflow order."""
        for n in nx.topological_sort(self._no_expr_graph):
            yield getattr(scope, n)
            
    def add(self, comp):
        """Add the name of a Component to the graph."""
        self._no_expr_graph.add_node(comp.name)

    def remove(self, comp):
        """Remove the name of a Component from the graph. It is not
        an error if the component is not found in the graph.
        """
        self._no_expr_graph.remove_node(comp.name)
        
    def connect(self, srcpath, destpath):
        """Add an edge to our Component graph from *srccompname* to *destcompname*.
        The *srcvarname* and *destvarname* args are for data reporting only.
        """
        # if an edge already exists between the two components, 
        # just increment the ref count
        graph = self._no_expr_graph
        srccompname, srcvarname = srcpath.split('.', 1)
        destcompname, destvarname = destpath.split('.', 1)
        try:
            graph[srccompname][destcompname]['refcount'] += 1
        except KeyError:
            graph.add_edge(srccompname, destcompname, refcount=1)
            
        if not is_directed_acyclic_graph(graph):
            # do a little extra work here to give more info to the user in the error message
            strongly_connected = strongly_connected_components(graph)
            refcount = graph[srccompname][destcompname]['refcount'] - 1
            if refcount == 0:
                graph.remove_edge(srccompname, destcompname)
            else:
                graph[srccompname][destcompname]['refcount'] = refcount
            for strcon in strongly_connected:
                if len(strcon) > 1:
                    raise RuntimeError(
                        'circular dependency (%s) would be created by connecting %s to %s' %
                                 (str(strcon), 
                                  '.'.join([srccompname,srcvarname]), 
                                  '.'.join([destcompname,destvarname]))) 
        
    def disconnect(self, comp1name, comp2name):
        """Decrement the ref count for the edge in the dependency graph 
        between the two components or remove the edge if the ref count
        reaches 0.
        """
        refcount = self._no_expr_graph[comp1name][comp2name]['refcount'] - 1
        if refcount == 0:
            self._no_expr_graph.remove_edge(comp1name, comp2name)
        else:
            self._no_expr_graph[comp1name][comp2name]['refcount'] = refcount
