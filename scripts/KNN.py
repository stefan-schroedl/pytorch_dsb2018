from sklearn.neighbors import KNeighborsClassifier
import numpy as np
from sklearn.feature_extraction.image import extract_patches_2d
from sklearn.feature_extraction.image import reconstruct_from_patches_2d
import cv2
import faiss   

class KNN():
    def __init__(self,n=5,patch_size=13,sample=100,gauss_blur=False,similarity=False,normalize=True):
        self.n=5
        self.channels=8
        self.patch_size=patch_size
        self.model =  KNeighborsClassifier(n_neighbors=n,n_jobs=-1,algorithm='kd_tree') 
        self.sample = sample
        self.patches = [] #np.array([]) 
        self.patches_3d = [] #np.array([])
	self.normalize = normalize
	gkernel=cv2.getGaussianKernel(ksize=patch_size,sigma=1)
	gkernel=gkernel*gkernel.T
	gkernel=gkernel.reshape(patch_size,patch_size,1)
	gkernel=np.concatenate((gkernel,gkernel,gkernel,gkernel,gkernel,gkernel),axis=2)
	gkernel=gkernel.reshape(-1)*self.patch_size*self.patch_size
        self.gkernel=gkernel
        self.similarity=similarity
        self.gauss_blur=gauss_blur
        self.faiss=True

    def prepare_fit(self,img,mask,mask_seg):
	img = (img.numpy()[0].transpose(1,2,0)*255).astype(np.uint8)
        mask = (mask.numpy()[0].transpose(1,2,0)).astype(np.uint8)
        mask_seg = (mask_seg.numpy()[0].transpose(1,2,0)*255).astype(np.uint8)

        super_boundary = mask.copy()[:,:,0]*0
        super_boundary_2 = mask.copy()[:,:,0]*0
        max_components=mask.max()
        kernel = np.ones((5,5), np.uint8)
        for x in xrange(max_components):
            this_one = ((mask==(x+1))*255).astype(np.uint8)[:,:,0]
            boundary = cv2.Laplacian(this_one,cv2.CV_8U,ksize=3)
            super_boundary = np.maximum(super_boundary,boundary)
            boundary = cv2.dilate(boundary, kernel, iterations=1)
            _,boundary_thresh = cv2.threshold(boundary,100,255,cv2.THRESH_BINARY)
            super_boundary_2 += boundary_thresh/255
        #print "X",super_boundary_2.max()
        super_boundary_2 = (super_boundary_2>1)*255
        #print super_boundary_2.sum(),super_boundary_2.max()
        #super_boundary_2 = np.minimum(super_boundary_2,3)
        #super_boundary_2 *= 85
        #cv2.imshow('super_boundary',super_boundary_2.astype(np.uint8))
        #cv2.imshow('mask',mask)
        #cv2.imshow('seg',mask_seg)
        #cv2.waitKey(1000)
        #img=img.numpy()[0]

        #convert mask_seg to mask
        #TODO!!!
        #get laplacian for all way boundary, for each mask laplace, then merge?
        #mask_seg=(mask_seg.numpy()[0].copy()*255).astype(np.uint8)
        #mask=mask.numpy()[0]
        #mask=np.minimum(mask,1)
        #mask*=255
        #boundary = cv2.Laplacian(mask_seg,cv2.CV_64F,ksize=3)
        boundary = cv2.Laplacian(mask_seg,cv2.CV_8U,ksize=3)
        boundary = boundary.reshape(boundary.shape[0],boundary.shape[1],1)
        assert(boundary.max()<=255)
        stacked_img = np.concatenate((img,mask_seg,boundary,np.maximum(mask_seg/2,boundary),super_boundary[:,:,None],super_boundary_2[:,:,None]),axis=2)
        data_patches = extract_patches_2d(stacked_img, (self.patch_size,self.patch_size) ,random_state=1000,max_patches=self.sample).astype(np.float64)
        #if self.patches.ndim==1:
        #    self.patches = data_patches.copy().reshape(data_patches.shape[0], -1)
        #else:
        #    self.patches = np.concatenate( (self.patches, data_patches.copy().reshape(data_patches.shape[0], -1)),axis=0 )
        self.patches.append(data_patches.reshape(-1))
	data_patches_3d = data_patches[:,:,:,:3].copy().reshape(data_patches.shape[0], -1)
	if self.normalize:
	    data_patches_3d -= np.mean(data_patches_3d, axis=0)
	    data_patches_3d /= np.std(data_patches_3d, axis=0)
        self.patches_3d.append(data_patches_3d.reshape(-1))
        #if self.patches_3d.ndim==1:
        #    self.patches_3d=data_patches_3d
        #else:
        #    self.patches_3d=np.concatenate( (self.patches_3d, data_patches_3d) , axis=0)

    def fit(self):
        c=self.patch_size*self.patch_size*self.channels
        self.patches_numpy = np.reshape(self.patches, newshape=(len(self.patches)*self.sample, c))
        c=self.patch_size*self.patch_size*3
        self.patches_3d_numpy = np.reshape(self.patches_3d, newshape=(len(self.patches_3d)*self.sample, c))
        if self.faiss:
            self.faiss_model = faiss.IndexFlatL2(self.patches_3d_numpy.shape[1])
            self.faiss_model.add(self.patches_3d_numpy.astype(np.float32))
        else:
            self.model.fit(self.patches_3d_numpy, np.zeros((len(self.patches_3d_numpy))))

    def predict(self,img):
	img = (img.numpy()[0].transpose(1,2,0)*255).astype(np.uint8)
        #cv2.imshow('predict img in',img)
        #cv2.waitKey(1)
        #img=img.numpy()[0]
        height,width,channels = img.shape
        img_patches = extract_patches_2d(img, (self.patch_size,self.patch_size)).astype(np.float64)
        img_patches = img_patches.reshape(img_patches.shape[0], -1)
        mean = np.mean(img_patches, axis=0)
        std = np.std(img_patches, axis=0)
	if self.normalize:
	    img_patches -= mean
	    img_patches /= std
        nearest_wds=None
        if self.faiss:
            nearest_wds=self.faiss_model.search(img_patches.astype(np.float32), self.n)
        else:
            nearest_wds=self.model.kneighbors(img_patches, return_distance=True)
	knn_patches=np.array([])
	for x in xrange(img_patches.shape[0]):
	    idxs=nearest_wds[1][x]

	    #use averaging
	    new_patch=self.patches_numpy[idxs].mean(axis=0)
	    #use similarity
	    if self.similarity:
		distances=nearest_wds[0][x]
		similarity=1.0/distances
		similarity/=similarity.sum()
		new_patch=(self.patches_numpy[idxs]*similarity[:,np.newaxis]).sum(axis=0)
	    #gaussian spread
	    if self.gauss_blur:
		new_patch=np.multiply(new_patch,self.gkernel)

	    if knn_patches.ndim==1:
		knn_patches=np.zeros((img_patches.shape[0],new_patch.shape[0]))
	    knn_patches[x]=new_patch
	knn_patches = knn_patches.reshape(knn_patches.shape[0], *(self.patch_size,self.patch_size,self.channels))
	reconstructed = reconstruct_from_patches_2d( knn_patches, (height, width,self.channels))
	reconstructed_img = reconstructed[:,:,:3].astype(np.uint8)
        #cv2.imshow('recon',reconstructed_img)
        #cv2.waitKey(10000)
	reconstructed_mask = reconstructed[:,:,3].astype(np.uint8)
	reconstructed_boundary = reconstructed[:,:,4].astype(np.uint8)
	reconstructed_blend = reconstructed[:,:,5].astype(np.uint8)
	reconstructed_super_boundary = reconstructed[:,:,6].astype(np.uint8)
	reconstructed_super_boundary_2 = reconstructed[:,:,7].astype(np.uint8)
        return reconstructed_img,reconstructed_mask,reconstructed_boundary,reconstructed_blend,reconstructed_super_boundary,reconstructed_super_boundary_2
        
        